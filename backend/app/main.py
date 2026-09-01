"""FastAPI 应用入口 — 见 docs/03-api.md。

新增(多用户 / session):
- 所有需要鉴权的接口都通过 Depends(get_current_user) 拿到当前用户。
- 静态挂载取消(原 /uploads, /outputs),改为 /api/files/{file_id} 与
  /api/jobs/{job_id}/output 两个带所有权校验的动态路由,跨用户拿不到文件。
- /api/sessions 系列:建 / 查 / 列 / 删 session,删时连带清掉该 session 的素材和产物。
- /api/upload 必填 session_id,文件落在 storage/users/{user_id}/sessions/{session_id}/uploads/。
- /api/render 必填 session_id,job 落入 jobs 表,产物落在 outputs/。

⚠️ TTS 多角色对话合成(2025-Q3 引入,当前版本已 DISABLED / DEPRECATED)⚠️
- 以下端点已全部用 `if False:` 包裹,不再注册到 FastAPI:
  /api/tts/import-asr  /api/tts  /api/tts/voices  /api/tts/from-job  /api/tts/by-source/{job_id}
- 详见 docs/Qwen3-TTS_MultiSpeaker_Dialogue_Guide.md(已标 DEPRECATED)。
- 恢复 Qwen3-TTS 集成时,把 if False 改成 if True 即可重新启用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
# 注:原 2025-Q3 版本还会 import Body(/api/tts/from-job 用)—— 当前版本已注释掉。
# from fastapi import Body  # noqa: E800 — Qwen3-TTS(已注释)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app import ai_service, db, queue
# 注:原 2025-Q3 版本还会 `from app import tts_service` —— TTS 多角色对话合成。
# 当前版本(回退 Qwen3-TTS)已注释掉。
# from app import tts_service  # noqa: E800 — Qwen3-TTS(已注释)

from app.auth import (
    SESSION_COOKIE_MAX_AGE,
    SESSION_COOKIE_NAME,
    CurrentUser,
    get_current_user,
)
from app.dsl import VideoDSL
from app.models import (
    CreateSessionRequest,
    FileInfo,
    JobStatus,
    JobSummary,
    SessionDetail,
    SessionInfo,
    UserInfo,
    # ⚠️ Qwen3-TTS 专用 Pydantic 模型(已注释):见下方 `if False:` 块。
    # FirstSegmentPreview,
    # TtsFromJobRequest,
    # TtsImportPreview,
    # TtsSubmitRequest,
)
from app import importer
from app.renderer import render_dsl
from app.storage import (
    ALLOWED_MIME,
    # EXT_AUDIO_WAV,  # noqa: E800 — Qwen3-TTS 产物扩展名(已注释)
    MAX_UPLOAD_SIZE,
    OUTPUT_EXT,
    OUTPUT_MIME,
    TIMELINE_MIME,
    output_path,
    remove_session,
    save_upload_bytes,
    timeline_path,
    upload_path,
    warn_legacy_storage,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "info").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("main")

warn_legacy_storage()

app = FastAPI(title="Dialogue Theater / 对话剧场", lifespan=queue.lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-User-Id"],
    # 允许跨域请求带 cookie(同源部署下默认就有,跨域调试 / 未来部署模式也需要)
    allow_credentials=True,
)


# ---------- 请求模型 ----------

class RenderRequest(BaseModel):
    dsl: VideoDSL
    session_id: str


class ImportResponse(BaseModel):
    dsl: VideoDSL
    uploaded_files: list[dict]
    warnings: list[str]


# ---------- AI 请求/响应模型 ----------


class GenerateDialogueRequest(BaseModel):
    session_id: str
    synopsis: str
    mode: str = "group"
    style_theme: str = "comic"
    intent: str = "short_video_drama"
    num_messages: int = 8


class ContinueDialogueRequest(BaseModel):
    session_id: str
    dsl: VideoDSL
    num_candidates: int = 3


class ContinueDialogueResponse(BaseModel):
    candidates: list[dict]


# ---------- 装饰器辅助 ----------

def _file_to_info(file_row: dict) -> FileInfo:
    return FileInfo(
        id=file_row["id"],
        session_id=file_row["session_id"],
        user_id=file_row["user_id"],
        kind=file_row["kind"],
        ext=file_row["ext"],
        size=file_row["size"],
        content_type=file_row.get("content_type"),
        created_at=file_row["created_at"],
        url=f"/api/files/{file_row['id']}",
    )


def _job_to_summary(job_row: dict) -> JobSummary:
    out = None
    timeline_url = None
    if job_row["status"] == "done":
        out = f"/api/jobs/{job_row['id']}/output"
        # 与 queue.get_job_status 保持一致:disk 上有 timeline.json 才暴露链接,
        # 老 job / 失败任务 / 透明产物下 timeline 缺失时留 None。
        tl = timeline_path(
            job_row["user_id"], job_row["session_id"], job_row["id"]
        )
        if tl.is_file():
            timeline_url = f"/api/jobs/{job_row['id']}/timeline"
    return JobSummary(
        id=job_row["id"],
        session_id=job_row["session_id"],
        user_id=job_row["user_id"],
        status=job_row["status"],
        progress=job_row["progress"],
        output_url=out,
        timeline_url=timeline_url,
        error=job_row["error"],
        created_at=job_row["created_at"],
        finished_at=job_row["finished_at"],
    )


def _decorate_session_sync(session_row: dict) -> SessionInfo:
    """同步版本 — 用于测试 / 同步装饰场景;async 路由统一用 _decorate_session。"""
    files = db.list_session_files(session_row["id"])
    jobs = db.list_session_jobs(session_row["id"])
    return SessionInfo(
        id=session_row["id"],
        user_id=session_row["user_id"],
        title=session_row["title"],
        created_at=session_row["created_at"],
        last_active_at=session_row["last_active_at"],
        file_count=len(files),
        job_count=len(jobs),
    )


async def _decorate_session(session_row: dict) -> SessionInfo:
    """async 路由装饰用 — 同步的 DB 调用走 to_thread,避免阻塞事件循环。"""
    sid = session_row["id"]
    files, jobs = await asyncio.gather(
        asyncio.to_thread(db.list_session_files, sid),
        asyncio.to_thread(db.list_session_jobs, sid),
    )
    return SessionInfo(
        id=sid,
        user_id=session_row["user_id"],
        title=session_row["title"],
        created_at=session_row["created_at"],
        last_active_at=session_row["last_active_at"],
        file_count=len(files),
        job_count=len(jobs),
    )


# ---------- 基础 ----------

@app.get("/health")
def health():
    return {"status": "ok", "workers": queue.WORKER_COUNT, "queue_size": queue.queue_size()}


@app.get("/api/me", response_model=UserInfo)
async def me(user: CurrentUser = Depends(get_current_user)):
    row = await db.upsert_user_async(user.id, user.username)
    return UserInfo(
        id=row["id"],
        username=row["username"],
        created_at=row["created_at"],
        registered_at=row.get("registered_at"),
        paid_at=row.get("paid_at"),
    )


# ---------- sessions ----------

@app.post("/api/sessions", response_model=SessionInfo, status_code=201)
async def create_session(
    body: CreateSessionRequest | None = None,
    response: Response = None,
    user: CurrentUser = Depends(get_current_user),
):
    """建一个新 session;前端在开始一次"任务"时调一次。

    响应同时 Set-Cookie(user_id) — 浏览器拿到 cookie 后,
    所有后续的 <img>/<iframe>/fetch 同源请求都能带身份鉴权。
    """
    session_id = uuid.uuid4().hex[:26]
    title = body.title if body else None
    row = await db.create_session_async(user.id, session_id, title)
    if response is not None:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=user.id,
            max_age=SESSION_COOKIE_MAX_AGE,
            path="/",
            samesite="lax",
            httponly=True,
        )
    return await _decorate_session(row)


@app.get("/api/sessions", response_model=list[SessionInfo])
async def list_sessions(user: CurrentUser = Depends(get_current_user)):
    rows = await asyncio.to_thread(db.list_user_sessions, user.id, 200)
    return [await _decorate_session(r) for r in rows]


@app.get("/api/sessions/{session_id}", response_model=SessionDetail)
async def get_session_detail(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    row = await asyncio.to_thread(db.get_session, session_id)
    if row is None or row["user_id"] != user.id:
        raise HTTPException(404, "session not found")
    files = await asyncio.to_thread(db.list_session_files, session_id)
    jobs = await asyncio.to_thread(db.list_session_jobs, session_id)
    return SessionDetail(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        created_at=row["created_at"],
        last_active_at=row["last_active_at"],
        file_count=len(files),
        job_count=len(jobs),
        files=[_file_to_info(f) for f in files],
        jobs=[_job_to_summary(j) for j in jobs],
    )


@app.delete("/api/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    row = await asyncio.to_thread(db.get_session, session_id)
    if row is None or row["user_id"] != user.id:
        raise HTTPException(404, "session not found")
    # 顺序:DB 事务先删(原子),成功后再清磁盘。
    # 删除 session 后其下属 files/jobs 会被 FK cascade / 显式 SQL 一并清掉,
    # 调用方拿删除计数,用于决策是否需要补删磁盘(但这里采用 rmtree 整目录,
    # 所以不需要)。
    await db.delete_session_cascade_async(session_id)
    # 磁盘清理:整个 session 目录 rmtree,不需要逐个 file_id 删。
    await asyncio.to_thread(remove_session, row["user_id"], session_id)
    return None


# ---------- 上传 ----------

@app.post("/api/upload", response_model=FileInfo)
async def upload(
    file: UploadFile = File(...),
    kind: str = Form("image"),
    session_id: str = Form(...),
    user: CurrentUser = Depends(get_current_user),
):
    if kind not in ("avatar", "image", "background"):
        raise HTTPException(400, "kind must be 'avatar', 'image' or 'background'")
    ext = ALLOWED_MIME.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(400, f"unsupported file type: {file.content_type}")

    sess = await asyncio.to_thread(db.get_session, session_id)
    if sess is None or sess["user_id"] != user.id:
        raise HTTPException(404, "session not found")

    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            413, f"file exceeds {MAX_UPLOAD_SIZE // (1024 * 1024)}MB limit"
        )

    file_id, _, _, content_type = await asyncio.to_thread(
        save_upload_bytes,
        user.id,
        session_id,
        data,
        ext,
        kind,
        content_type=file.content_type,
    )
    row = await db.insert_file_async(
        file_id=file_id,
        session_id=session_id,
        user_id=user.id,
        kind=kind,
        ext=ext,
        size=len(data),
        content_type=content_type,
    )
    await db.touch_session_async(session_id)
    logger.info(
        "Upload %s kind=%s bytes=%d user=%s session=%s",
        file_id, kind, len(data), user.id, session_id,
    )
    return _file_to_info(row)


# ---------- 导入 ----------

@app.post("/api/import", response_model=ImportResponse)
async def import_package_route(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    user: CurrentUser = Depends(get_current_user),
):
    """导入 zip(DSL + 图片素材)到当前 session,返回改写后的 DSL。"""
    sess = await asyncio.to_thread(db.get_session, session_id)
    if sess is None or sess["user_id"] != user.id:
        raise HTTPException(404, "session not found")

    zip_bytes = await file.read()
    try:
        result = await asyncio.to_thread(
            importer.import_package,
            zip_bytes=zip_bytes,
            session_id=session_id,
            user_id=user.id,
        )
    except importer.PackageError as exc:
        raise HTTPException(exc.http_status, {"code": exc.code, **exc.detail})

    await db.touch_session_async(session_id)
    logger.info(
        "Import user=%s session=%s files=%d warnings=%d",
        user.id, session_id, len(result.uploaded_files), len(result.warnings),
    )
    return ImportResponse(
        dsl=result.dsl,
        uploaded_files=[
            {
                "path_in_zip": f.path_in_zip,
                "file_id": f.file_id,
                "url": f.url,
                "kind": f.kind,
                "size": f.size,
                "deduped": f.deduped,
            }
            for f in result.uploaded_files
        ],
        warnings=result.warnings,
    )


# ---------- AI 辅助生成 ----------


@app.get("/api/ai/health")
async def ai_health():
    """检查 AI 接口连通性，不消耗额度，无需鉴权（方便运维排查）。"""
    return await ai_service.check_ai_connection()


@app.get("/api/ai/quota")
async def ai_quota(user: CurrentUser = Depends(get_current_user)):
    """查询当前用户今日 AI 生成额度。"""
    return ai_service.get_quota_status(user.id)


@app.post("/api/ai/generate-dialogue", response_model=VideoDSL)
async def ai_generate_dialogue(
    body: GenerateDialogueRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """根据剧情概要生成完整对话 DSL。"""
    sess = await asyncio.to_thread(db.get_session, body.session_id)
    if sess is None or sess["user_id"] != user.id:
        raise HTTPException(404, "session not found")

    try:
        dsl = await ai_service.generate_dialogue(
            user_id=user.id,
            synopsis=body.synopsis,
            mode=body.mode,
            style_theme=body.style_theme,
            intent=body.intent,
            num_messages=body.num_messages,
        )
    except ai_service.AIServiceError as exc:
        status_code = 503 if exc.code in ("not_configured", "upstream_error", "timeout", "connect_error") else 429 if exc.code == "quota_exceeded" else 400
        raise HTTPException(status_code, {"code": exc.code, "reason": str(exc)})

    await db.touch_session_async(body.session_id)
    return dsl


@app.post("/api/ai/continue-dialogue", response_model=ContinueDialogueResponse)
async def ai_continue_dialogue(
    body: ContinueDialogueRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """基于已有 DSL 续写候选消息。"""
    sess = await asyncio.to_thread(db.get_session, body.session_id)
    if sess is None or sess["user_id"] != user.id:
        raise HTTPException(404, "session not found")

    try:
        candidates = await ai_service.continue_dialogue(
            user_id=user.id,
            current_scene=body.dsl.scene,
            num_candidates=body.num_candidates,
        )
    except ai_service.AIServiceError as exc:
        status_code = 503 if exc.code in ("not_configured", "upstream_error", "timeout", "connect_error") else 429 if exc.code == "quota_exceeded" else 400
        raise HTTPException(status_code, {"code": exc.code, "reason": str(exc)})

    await db.touch_session_async(body.session_id)
    return ContinueDialogueResponse(
        candidates=[c.model_dump(mode="json") for c in candidates]
    )


# ---------- TTS 多角色对话合成(2025-Q3,DISABLED / DEPRECATED) ----------


if False:  # noqa: E800 — Qwen3-TTS 多角色对话合成(已禁用),恢复时改 if True
    # 注:下方端点注册代码原样保留,wrap 在 `if False:` 内,不再暴露到 FastAPI。
    # 恢复时仅需把 `if False:` 改为 `if True:`,并取消文件顶部对应
    # `from app import tts_service` 与 `FirstSegmentPreview` / `TtsFromJobRequest` /
    # `TtsImportPreview` / `TtsSubmitRequest` 的 import 注释即可。

    @app.post("/api/tts/import-asr", response_model=TtsImportPreview)
    async def import_asr(
        file: UploadFile = File(...),
        session_id: str = Form(...),
        user: CurrentUser = Depends(get_current_user),
    ):
        """上传 + 解析 + 预览一次返回。

        复用 storage.save_upload_bytes + db.insert_file 落盘入库,kind="asr" 区别于
        通用素材(avatar/image/background)。ASR JSON 不是 DSL 引用资源,只是 TTS 任务
        的输入参数,所以这里不复用 /api/upload 的 kind 白名单。

        失败:
          - 文件超过 MAX_UPLOAD_SIZE → 413
          - JSON 解析失败 / 结构不合法 → 400 + {"code": "bad_asr", ...}
          - session 不存在或不属于当前用户 → 404
        """
        sess = await asyncio.to_thread(db.get_session, session_id)
        if sess is None or sess["user_id"] != user.id:
            raise HTTPException(404, "session not found")

        data = await file.read()
        if not data:
            raise HTTPException(400, "empty file")
        if len(data) > MAX_UPLOAD_SIZE:
            raise HTTPException(
                413, f"file exceeds {MAX_UPLOAD_SIZE // (1024 * 1024)}MB limit"
            )

        try:
            parsed_raw = json.loads(data.decode("utf-8"))
        except Exception as exc:
            raise HTTPException(400, f"not valid JSON: {exc}")

        try:
            preview = tts_service.parse_asr_json(parsed_raw)
        except tts_service.AsrParseError as exc:
            raise HTTPException(400, {"code": "bad_asr", "reason": str(exc)})

        # 落盘 + 入库(不复用 /api/upload,因为 kind="asr" 不在它白名单里)
        file_id, _, _, _ = await asyncio.to_thread(
            save_upload_bytes,
            user.id,
            session_id,
            data,
            "json",
            "asr",
            content_type="application/json",
        )
        row = await db.insert_file_async(
            file_id=file_id,
            session_id=session_id,
            user_id=user.id,
            kind="asr",
            ext="json",
            size=len(data),
            content_type="application/json",
        )
        await db.touch_session_async(session_id)
        logger.info(
            "TTS import-asr user=%s session=%s file=%s segments=%d",
            user.id, session_id, file_id, preview["segments_count"],
        )

        first = preview["first_segment_preview"]
        return TtsImportPreview(
            file_id=file_id,
            url=f"/api/files/{file_id}",
            segments_count=preview["segments_count"],
            total_duration_ms=preview["total_duration_ms"],
            speakers=preview["speakers"],
            speaker_segments=preview["speaker_segments"],
            first_segment_preview=(
                FirstSegmentPreview(**first) if first else None
            ),
        )


    @app.post("/api/tts", status_code=202)
    async def submit_tts(
        body: TtsSubmitRequest,
        user: CurrentUser = Depends(get_current_user),
    ):
        """提交一次多角色对话合成任务。返回 { job_id, status: "queued" }。

        校验链(顺序故意调过):
          1. session 所有权 → 否则 404(用户传错 session_id 必须先暴露这个问题);
          2. asr_file_id 所有权 + kind == "asr" → 否则 404 / 400;
          3. TTS_ENABLED / TTS_MODEL_PATH → 否则 503;
          4. 入队 jobs 表(kind="tts", output_ext="wav"),config_json 落整个 body 序列化结果。

        如果先做 TTS 可用性检查,用户传错 session_id 会被吞成 503,运维和前端都要多走
        一圈才能定位问题。
        """
        # 1. session 所有权
        sess = await asyncio.to_thread(db.get_session, body.session_id)
        if sess is None or sess["user_id"] != user.id:
            raise HTTPException(404, "session not found")

        # 2. asr_file_id 所有权 + 类型
        asr_row = await asyncio.to_thread(db.get_file, body.asr_file_id)
        if asr_row is None or asr_row["user_id"] != user.id or asr_row["session_id"] != body.session_id:
            raise HTTPException(404, "ASR file not found")
        if asr_row.get("kind") != "asr":
            raise HTTPException(
                400, f"file kind must be 'asr', got {asr_row.get('kind')!r}"
            )

        # 3. TTS 可用性(放到 session / file 校验之后)
        if not tts_service.TTS_ENABLED:
            raise HTTPException(503, "TTS is disabled (set TTS_ENABLED=true)")
        if not tts_service.TTS_MODEL_PATH and not body.model_path:
            raise HTTPException(
                503,
                "TTS_MODEL_PATH not configured; set it in env or pass model_path",
            )

        # 4. 入队;config_json = 整个 body dump,worker 端不再读请求体
        config = body.model_dump(mode="json")
        try:
            job_id = await queue.enqueue_tts(
                tts_config=config,
                session_id=body.session_id,
                user_id=user.id,
            )
        except queue.QueueFullError:
            raise HTTPException(503, "queue is full, please try again later")

        logger.info(
            "TTS submit user=%s session=%s asr=%s job=%s",
            user.id, body.session_id, body.asr_file_id, job_id,
        )
        return {"job_id": job_id, "status": "queued"}


    @app.get("/api/tts/voices")
    async def tts_voices(user: CurrentUser = Depends(get_current_user)):
        """调试端点:返回当前 TTS_VOICE_CONFIG + model.get_supported_speakers() 实际查询结果。

        模型没加载就 503(避免无脑触发一次 1-2 分钟的 GPU 加载):
          - TTS_ENABLED=false → 503
          - TTS_MODEL_PATH 与 per-task model_path 都为空 → 503
          - get_supported_speakers 抛 RuntimeError → 503 + reason
        """
        if not tts_service.TTS_ENABLED:
            raise HTTPException(503, "TTS is disabled")
        if not tts_service.TTS_MODEL_PATH:
            # /api/tts/voices 不接受 per-task override,所以只看 env
            raise HTTPException(503, "TTS_MODEL_PATH not configured")
        try:
            speakers = await tts_service.get_supported_speakers()
        except RuntimeError as exc:
            raise HTTPException(503, f"TTS model unavailable: {exc}")
        return {
            "config": tts_service.get_voice_config(),
            "available_speakers": speakers,
        }


    @app.post("/api/tts/from-job", status_code=202)
    async def submit_tts_from_job(
        body: TtsFromJobRequest = Body(...),
        user: CurrentUser = Depends(get_current_user),
    ):
        """从已渲染视频任务派生 ASR → 入队 TTS 任务。

        用途:时间码页「生成语音」按钮 — 用户不必再手填 ASR JSON,
        后端从 render 任务的 config_json 里抽对话文本直接合成。

        校验链(跟 submit_tts 对齐):
          1. source job 存在 + user 所有权 + kind="render" → 否则 404;
             (kind 不对也按 404 处理,不暴露存在性)
          2. source job.status == "done" → 否则 409;
             (status 提前到 TTS 可用性之前 — 任务未完成是用户问题,
              TTS 没配是环境问题,两者语义不同,先报用户面问题更直观)
          3. TTS_ENABLED / TTS_MODEL_PATH → 否则 503;
          4. build_asr_from_dsl 解析失败 → 400(DSL 损坏 / 空消息);
          5. ASR JSON 落盘(save_upload_bytes,ext="json")+ db.insert_file(kind="asr");
          6. 入队 tts 任务,config_json 塞 {"asr_file_id", "source_job_id",
             "role_map": {}, "instructs": {}};
          7. 返回 { "tts_job_id": <新 job_id>, "status": "queued" }。
        """
        # 1. source job 校验
        src = await db.get_job_async(body.job_id)
        if src is None or src["user_id"] != user.id or src.get("kind", "render") != "render":
            raise HTTPException(404, "video job not found")

        # 2. source job 必须 done(用户面问题,先于 TTS 环境检查)
        if src["status"] != "done":
            raise HTTPException(409, f"video job not finished (status={src['status']})")

        # 3. TTS 可用性
        if not tts_service.TTS_ENABLED:
            raise HTTPException(503, "TTS is disabled (set TTS_ENABLED=true)")
        if not tts_service.TTS_MODEL_PATH:
            raise HTTPException(503, "TTS_MODEL_PATH not configured")

        # 4. build ASR + 兜底解析校验(parse_asr_json 抛错就 400)
        try:
            dsl = VideoDSL.model_validate(src["config"])
            asr_payload = tts_service.build_asr_from_dsl(dsl)
            tts_service.parse_asr_json(asr_payload)  # 校验结构
        except tts_service.AsrParseError as exc:
            raise HTTPException(400, {"code": "bad_asr", "reason": str(exc)})
        except Exception as exc:  # noqa: BLE001 — VideoDSL 解析错也算 400
            raise HTTPException(400, f"failed to derive ASR from DSL: {exc}")

        # 5. ASR JSON 落盘 + 入库
        asr_bytes = json.dumps(asr_payload, ensure_ascii=False).encode()
        file_id, _, _, _ = await asyncio.to_thread(
            save_upload_bytes,
            user.id,
            src["session_id"],
            asr_bytes,
            "json",
            "asr",
            content_type="application/json",
        )
        await db.insert_file_async(
            file_id=file_id,
            session_id=src["session_id"],
            user_id=user.id,
            kind="asr",
            ext="json",
            size=len(asr_bytes),
            content_type="application/json",
        )

        # 6. 入队(per-task role_map/instructs 留空,沿用全局默认)
        tts_config = {
            "asr_file_id": file_id,
            "source_job_id": body.job_id,
            "role_map": {},
            "instructs": {},
        }
        try:
            tts_job_id = await queue.enqueue_tts(
                tts_config=tts_config,
                session_id=src["session_id"],
                user_id=user.id,
            )
        except queue.QueueFullError:
            raise HTTPException(503, "queue is full, please try again later")

        logger.info(
            "TTS from-job: user=%s render=%s asr=%s tts=%s",
            user.id, body.job_id, file_id, tts_job_id,
        )
        return {"tts_job_id": tts_job_id, "status": "queued"}


    @app.get("/api/tts/by-source/{job_id}")
    async def tts_by_source_job(
        job_id: str,
        user: CurrentUser = Depends(get_current_user),
    ):
        """时间码页持久化查询:返回该 render job 最近一个 TTS 子任务的状态。

        契约:
          - 找到 → 200 + body(含 tts_job_id / status / progress / output_url /
            error / metadata_json);
          - 没找到 → 200 + body=None(不是 404;前端据此判断是否要显示「生成语音」按钮)。

        实现走 db.find_latest_tts_by_source:jobs 表里 kind="tts" AND
        user_id=user.id AND config_json LIKE '%"source_job_id":"<job_id>"%' →
        ORDER BY created_at DESC LIMIT 1。
        """
        row = await asyncio.to_thread(db.find_latest_tts_by_source, user.id, job_id)
        if row is None:
            return None
        out_url: str | None = None
        if row["status"] == "done":
            out_url = f"/api/jobs/{row['id']}/output"
        return {
            "tts_job_id": row["id"],
            "status": row["status"],
            "progress": row["progress"],
            "output_url": out_url,
            "error": row.get("error"),
            "metadata_json": row.get("metadata_json"),
        }


# ---------- 文件 / 产物访问(带所有权校验) ----------

@app.get("/api/files/{file_id}")
async def serve_file(
    file_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    row = await asyncio.to_thread(db.get_file, file_id)
    if row is None or row["user_id"] != user.id:
        raise HTTPException(404, "file not found")
    p = upload_path(row["user_id"], row["session_id"], row["id"], row["ext"])
    if not p.is_file():
        raise HTTPException(404, "file missing on disk")
    media = row.get("content_type") or "application/octet-stream"
    return FileResponse(p, media_type=media)


@app.get("/api/jobs/{job_id}/output")
async def serve_output(
    job_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    row = await asyncio.to_thread(db.get_job, job_id)
    if row is None or row["user_id"] != user.id:
        raise HTTPException(404, "job not found")
    if row["status"] != "done":
        raise HTTPException(409, "job not finished")
    ext = row.get("output_ext") or OUTPUT_EXT
    p = output_path(row["user_id"], row["session_id"], row["id"], ext)
    if not p.is_file():
        raise HTTPException(404, "output missing on disk")
    # 透明背景产物走 video/webm (VP9+alpha) 或 video/quicktime (ProRes 4444);
    # 旧 mp4 任务保持 video/mp4;TTS 任务(2025-Q3)走 audio/wav 触发浏览器 <audio> 播放。
    # ext 白名单由 db.insert_job 强制(mp4/webm/mov/wav),这里不需要再校验。
    media_type = OUTPUT_MIME.get(ext, "application/octet-stream")
    return FileResponse(p, media_type=media_type, filename=f"{row['id']}.{ext}")


@app.get("/api/jobs/{job_id}/timeline")
async def serve_timeline(
    job_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """返回时间码 JSON(见 docs/03-api.md §3.x 时间码导出 + docs/04-template.md §4.14)。

    所有权 / 完成态 / 磁盘存在性校验与 `serve_output` 同模板:
      - 任务不存在或不属于当前用户 → 404(不泄露存在性)
      - 任务未完成 → 409
      - timeline.json 缺失 → 404(产物存在但 timeline 不存在:老 job / 透明
        路径下编码失败等 — 前端按钮会因 timeline_url=None 而隐藏,这里再补
        一道 404 防止直链访问)
    """
    row = await asyncio.to_thread(db.get_job, job_id)
    if row is None or row["user_id"] != user.id:
        raise HTTPException(404, "job not found")
    if row["status"] != "done":
        raise HTTPException(409, "job not finished")
    p = timeline_path(row["user_id"], row["session_id"], row["id"])
    if not p.is_file():
        raise HTTPException(404, "timeline missing on disk")
    return FileResponse(p, media_type=TIMELINE_MIME, filename=f"{row['id']}.timeline.json")


# ---------- 预览 / 渲染 ----------

@app.post("/api/preview-html")
async def preview_html(
    body: RenderRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """接收 VideoDSL + session_id,返回拼好的 HTML(只拼模板,不录制)。

    与 /api/render 同样鉴权 + session 归属校验,避免渲染 HTML 被任意访问
    与 session 枚举。渲染走 to_thread,避免 CPU 密集的 Jinja 阻塞事件循环。

    预览模式下注入一段 CSS 隐藏 `#intro-typewriter-text` —— 这个元素只在
    green_screen 模板的 typewriter 模式下出现,目的是让抠像输出保留中间的打字机字
    (因为顶部标题栏在绿幕下也会被抠掉)。但预览里它与顶部 #theater-title 的
    打字机效果重复,显得多余;实际录制(透明/不透明两条路径)必须保留这个元素。
    """
    sess = await asyncio.to_thread(db.get_session, body.session_id)
    if sess is None or sess["user_id"] != user.id:
        raise HTTPException(404, "session not found")
    html = await asyncio.to_thread(render_dsl, body.dsl)
    preview_only_css = (
        "<style>/* preview-only: hide green_screen mid-screen typewriter text"
        " (kept in real render for keying) */"
        "#intro-typewriter-text { display: none !important; }</style>"
    )
    html = html.replace("</head>", preview_only_css + "</head>", 1)
    return {"html": html}


@app.post("/api/render", status_code=202)
async def render(
    body: RenderRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """接收 VideoDSL + session_id,入队,返回 job_id。"""
    sess = await asyncio.to_thread(db.get_session, body.session_id)
    if sess is None or sess["user_id"] != user.id:
        raise HTTPException(404, "session not found")
    try:
        job_id = await queue.enqueue(body.dsl, body.session_id, user.id)
    except queue.QueueFullError:
        raise HTTPException(503, "queue is full, please try again later")
    logger.info(
        "Render requested, job=%s user=%s session=%s",
        job_id, user.id, body.session_id,
    )
    return {"job_id": job_id}


# ---------- 任务状态 / SSE ----------

@app.get("/api/jobs/{job_id}", response_model=JobStatus)
async def job_status(
    job_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    status = await queue.get_job_status(job_id, user_id=user.id)
    if status is None:
        raise HTTPException(404, "job not found")
    return JobStatus(**status)


def _sse(event_type: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=True)
    return f"event: {event_type}\ndata: {payload}\n\n"


def _event_type(ev: dict) -> str:
    if ev["status"] == "done":
        return "done"
    if ev["status"] == "failed":
        return "failed"
    return "progress"


@app.get("/api/jobs/{job_id}/events")
async def job_events(
    job_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    job = await queue.get_job_for_user(job_id, user.id)
    if job is None:
        raise HTTPException(404, "job not found")
    tl_initial = timeline_path(job["user_id"], job["session_id"], job["id"])
    snap = {
        "id": job["id"],
        "status": job["status"],
        "progress": job["progress"],
        "error": job.get("error"),
        "output_url": f"/api/jobs/{job['id']}/output",
        # SSE 初始快照里也带 output_ext,前端订阅时立即知道产物格式。
        "output_ext": job.get("output_ext"),
        # timeline.json disk 上存在时附带链接,前端 SSE 立刻就能看到「查看时间码」按钮。
        "timeline_url": (
            f"/api/jobs/{job['id']}/timeline" if tl_initial.is_file() else None
        ),
    }

    async def event_stream():
        cur = await queue.current_event(snap)
        yield _sse(_event_type(cur), cur)
        if job["status"] in ("done", "failed"):
            return

        q = queue.subscribe(job_id)
        try:
            latest = await db.get_job_async(job_id)
            if latest is not None and latest["status"] in ("done", "failed"):
                tl2 = timeline_path(
                    latest["user_id"], latest["session_id"], latest["id"]
                )
                snap2 = {
                    "id": latest["id"],
                    "status": latest["status"],
                    "progress": latest["progress"],
                    "error": latest.get("error"),
                    "output_url": f"/api/jobs/{latest['id']}/output",
                    "output_ext": latest.get("output_ext"),
                    "timeline_url": (
                        f"/api/jobs/{latest['id']}/timeline"
                        if tl2.is_file()
                        else None
                    ),
                }
                cur2 = await queue.current_event(snap2)
                yield _sse(_event_type(cur2), cur2)
                return
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                etype = _event_type(event)
                yield _sse(etype, event)
                if event["status"] in ("done", "failed"):
                    break
        finally:
            queue.unsubscribe(job_id, q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------- 内部管理(注册/充值标记) ----------


@app.post("/api/admin/users/{user_id}/register", response_model=UserInfo)
async def admin_register_user(
    user_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """标记指定用户已注册。当前仅允许用户自己操作自己的注册状态;后续可扩展管理员鉴权。"""
    if current_user.id != user_id:
        raise HTTPException(403, "can only register yourself")
    row = await db.mark_user_registered_async(user_id)
    if row is None:
        raise HTTPException(404, "user not found")
    return UserInfo(**row)


@app.post("/api/admin/users/{user_id}/recharge", response_model=UserInfo)
async def admin_recharge_user(
    user_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """标记指定用户已充值/付费。当前仅允许用户自己操作自己的付费状态;后续可扩展管理员鉴权。"""
    if current_user.id != user_id:
        raise HTTPException(403, "can only recharge yourself")
    row = await db.mark_user_paid_async(user_id)
    if row is None:
        raise HTTPException(404, "user not found")
    return UserInfo(**row)
