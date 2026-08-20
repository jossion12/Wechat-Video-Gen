"""FastAPI 应用入口 — 见 docs/03-api.md。

新增(多用户 / session):
- 所有需要鉴权的接口都通过 Depends(get_current_user) 拿到当前用户。
- 静态挂载取消(原 /uploads, /outputs),改为 /api/files/{file_id} 与
  /api/jobs/{job_id}/output 两个带所有权校验的动态路由,跨用户拿不到文件。
- /api/sessions 系列:建 / 查 / 列 / 删 session,删时连带清掉该 session 的素材和产物。
- /api/upload 必填 session_id,文件落在 storage/users/{user_id}/sessions/{session_id}/uploads/。
- /api/render 必填 session_id,job 落入 jobs 表,产物落在 outputs/。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app import db, queue
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
)
from app import importer
from app.renderer import render_dsl
from app.storage import (
    ALLOWED_MIME,
    MAX_UPLOAD_SIZE,
    OUTPUT_EXT,
    output_path,
    remove_session,
    save_upload_bytes,
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
    if job_row["status"] == "done":
        out = f"/api/jobs/{job_row['id']}/output"
    return JobSummary(
        id=job_row["id"],
        session_id=job_row["session_id"],
        user_id=job_row["user_id"],
        status=job_row["status"],
        progress=job_row["progress"],
        output_url=out,
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
    p = output_path(row["user_id"], row["session_id"], row["id"],
                    row.get("output_ext") or OUTPUT_EXT)
    if not p.is_file():
        raise HTTPException(404, "output missing on disk")
    return FileResponse(p, media_type="video/mp4", filename=f"{row['id']}.mp4")


# ---------- 预览 / 渲染 ----------

@app.post("/api/preview-html")
async def preview_html(
    body: RenderRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """接收 VideoDSL + session_id,返回拼好的 HTML(只拼模板,不录制)。

    与 /api/render 同样鉴权 + session 归属校验,避免渲染 HTML 被任意访问
    与 session 枚举。渲染走 to_thread,避免 CPU 密集的 Jinja 阻塞事件循环。
    """
    sess = await asyncio.to_thread(db.get_session, body.session_id)
    if sess is None or sess["user_id"] != user.id:
        raise HTTPException(404, "session not found")
    html = await asyncio.to_thread(render_dsl, body.dsl)
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
    snap = {
        "id": job["id"],
        "status": job["status"],
        "progress": job["progress"],
        "error": job.get("error"),
        "output_url": f"/api/jobs/{job['id']}/output",
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
                snap2 = {
                    "id": latest["id"],
                    "status": latest["status"],
                    "progress": latest["progress"],
                    "error": latest.get("error"),
                    "output_url": f"/api/jobs/{latest['id']}/output",
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
