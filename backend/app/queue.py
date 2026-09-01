"""asyncio 任务队列 + worker 池 — 见 docs/01-architecture.md §D2、docs/03-api.md §3.4。

任务状态全部落 SQLite(见 app.db),重启不丢;队列本身仍然是 asyncio.Queue,
worker 数由 WORKER_COUNT 控制;队列满抛 QueueFullError,上层转 503。

SSE 仍然用内存订阅队列:_subscribers[job_id] = list[asyncio.Queue],
原因是 SSE 推送是高频的短事件,过 DB 既慢又复杂,启动时 worker 会把已存在的
'running' / 'queued' 任务重新入队(见 _rehydrate_jobs_async)。
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

from app import db, recorder
# 注:原 2025-Q3 版本还会 `from app import tts_service` —— TTS 多角色对话合成。
# 当前版本(回退 Qwen3-TTS)已注释掉,模块不导入即可。
# from app import tts_service  # noqa: E800 — Qwen3-TTS(已注释)
from app.dsl import VideoDSL
# EXT_AUDIO_WAV 原用于 TTS 多角色对话合成产物(wav),当前版本注释保留。
from app.storage import (
    timeline_path,
    # EXT_AUDIO_WAV,  # noqa: E800 — Qwen3-TTS(已注释)
)

logger = logging.getLogger("queue")

WORKER_COUNT = int(os.getenv("WORKER_COUNT", "2"))
MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", "100"))

# 透明背景 DSL → 产物扩展名映射。job 入库时写入 jobs.output_ext,
# serve_output 按这个 ext 拿文件 + 拼 MIME;worker 也靠它决定是否走透明路径。
# transparent_format 缺省 → webm_vp9_alpha(体量更小、跨平台兼容性更好)。
_TRANSPARENT_FORMAT_TO_EXT = {
    "webm_vp9_alpha": "webm",
    "mov_prores4444": "mov",
}


def _resolve_output_ext(dsl: VideoDSL) -> str:
    """从 DSL 推出产物扩展名,默认 mp4。"""
    if dsl.transparent:
        fmt = dsl.transparent_format or "webm_vp9_alpha"
        return _TRANSPARENT_FORMAT_TO_EXT.get(fmt, "mp4")
    return "mp4"


class QueueFullError(Exception):
    """队列已满。"""


_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
_subscribers: dict[str, list[asyncio.Queue]] = {}


# ---------- 对外接口 ----------

async def enqueue(dsl: VideoDSL, session_id: str, user_id: str) -> str:
    """入队并返回 job_id;队列满抛 QueueFullError。"""
    if _queue.full():
        raise QueueFullError("queue is full")
    job_id = uuid.uuid4().hex[:26]
    config = dsl.model_dump(mode="json")
    output_ext = _resolve_output_ext(dsl)
    await db.insert_job_async(
        job_id=job_id,
        session_id=session_id,
        user_id=user_id,
        config=config,
        output_ext=output_ext,
        kind="render",
    )
    await db.touch_session_async(session_id)
    _queue.put_nowait(job_id)
    logger.info(
        "Job %s queued (user=%s session=%s output_ext=%s)",
        job_id, user_id, session_id, output_ext,
    )
    return job_id


async def enqueue_tts(tts_config: dict, session_id: str, user_id: str) -> str:
    """⚠️ 入队一个 TTS 多角色对话合成任务(2025-Q3 新增,DISABLED / DEPRECATED)⚠️

    当前版本(回退 Qwen3-TTS)本函数不再被 main.py 调用,直接 raise 兜底防止误用。
    与 enqueue() 平级:同一 asyncio.Queue、同一组 worker,
    _process_job 按 jobs.kind 分发到 tts_service.synthesize()。

    见 docs/Qwen3-TTS_MultiSpeaker_Dialogue_Guide.md(已标 DEPRECATED)。
    """
    raise NotImplementedError(
        "enqueue_tts 已 DISABLED(DISABLED / DEPRECATED)。"
        "回退 Qwen3-TTS 集成期间禁止调用,见 docs/Qwen3-TTS_MultiSpeaker_Dialogue_Guide.md。"
    )


async def get_job_status(job_id: str, user_id: str | None = None) -> dict | None:
    """返回任务状态 dict(供 API 层包装);非本用户的 job 返回 None(等同 404)。"""
    job = await db.get_job_async(job_id)
    if job is None:
        return None
    if user_id is not None and job["user_id"] != user_id:
        # 跨用户访问隐藏存在性
        return None
    if job["status"] == "done":
        out = job.get("output_url") or f"/api/jobs/{job['id']}/output"
        # timeline.json 与 mp4/webm/mov 一起在 recorder 里落地,disk 上存在才暴露 URL。
        # 老 job 没 timeline.json 时 timeline_url 留 None,前端按钮不显示,不影响下载。
        # ⚠️ TTS 任务曾有 timeline_url 路径的概念,2025-Q3 Qwen3-TTS 集成期间
        # 不会写 timeline.json。当前版本(回退 Qwen3-TTS)此处语义照旧。
        tl = timeline_path(job["user_id"], job["session_id"], job["id"])
        timeline_url = (
            f"/api/jobs/{job['id']}/timeline" if tl.is_file() else None
        )
    else:
        out = None
        timeline_url = None
    return {
        "id": job["id"],
        "status": job["status"],
        "progress": job["progress"],
        "output_url": out,
        "error": job["error"],
        "created_at": job["created_at"],
        "finished_at": job["finished_at"],
        # 透传到前端,让下载按钮 / 文件名按实际产物走。
        # 老数据里这列是空(列是后续迁移加的,见 db._ensure_columns),
        # 前端在 ProgressPanel 拿不到时按 'mp4' 兜底,不破坏 UI。
        "output_ext": job.get("output_ext"),
        "timeline_url": timeline_url,
        # ⚠️ kind 字段(2025-Q3 引入,Qwen3-TTS pipeline):前端按 kind 路由下载/播放 UI;
        # 当前版本仅在 db 层读出,渲染层只可能拿到 "render"。老 job 走
        # _ensure_columns 兼容迁移落 "render"。
        "kind": job.get("kind", "render"),
        # ⚠️ TTS 单段失败明细 —— Qwen3-TTS(已注释):
        # 仅 kind="tts" 的 done 任务里非空;当前版本(回退 Qwen3-TTS)此字段永远为 None,
        # db 层仍保留 metadata_json 列以避免破坏已迁移数据库。
        # "metadata_json": job.get("metadata_json"),  # noqa: E800 — Qwen3-TTS(已注释)
    }


async def get_job_for_user(job_id: str, user_id: str) -> dict | None:
    """取完整 job 信息(含 config),用于 worker 或 session 详情。"""
    job = await db.get_job_async(job_id)
    if job is None or job["user_id"] != user_id:
        return None
    return job


def queue_size() -> int:
    return _queue.qsize()


# ---------- SSE 订阅 ----------

def subscribe(job_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.setdefault(job_id, []).append(q)
    return q


def unsubscribe(job_id: str, q: asyncio.Queue) -> None:
    subs = _subscribers.get(job_id)
    if subs:
        try:
            subs.remove(q)
        except ValueError:
            pass
        if not subs:
            _subscribers.pop(job_id, None)


async def current_event(job: dict) -> dict:
    """SSE 初始快照 / 最终状态事件。"""
    if job["status"] == "failed":
        return {
            "status": "failed",
            "progress": 0,
            "error": job.get("error"),
            "kind": job.get("kind", "render"),
        }
    if job["status"] == "done":
        # SSE done 事件里把 timeline_url 一起带上,前端无需再额外轮询一次
        # GET /api/jobs/{id} 就能立刻看到「查看时间码」按钮。
        tl = timeline_path(job["user_id"], job["session_id"], job["id"])
        timeline_url = (
            f"/api/jobs/{job['id']}/timeline" if tl.is_file() else None
        )
        return {
            "status": "done",
            "progress": 100,
            "output_url": job.get("output_url") or f"/api/jobs/{job['id']}/output",
            "output_ext": job.get("output_ext"),
            "timeline_url": timeline_url,
            # ⚠️ kind 字段(2025-Q3 引入,Qwen3-TTS pipeline):前端按 kind 区分 UI;
            # 当前版本(回退 Qwen3-TTS)kind 仅作读出保留,渲染层只可能拿到 "render"。
            "kind": job.get("kind", "render"),
            # ⚠️ TTS done 事件 metadata_json —— Qwen3-TTS(已注释)
            # 当前版本(回退 Qwen3-TTS)此字段永远为 None,保留注释方便恢复。
            # "metadata_json": job.get("metadata_json"),  # noqa: E800 — Qwen3-TTS(已注释)
        }
    return {
        "status": job["status"],
        "progress": job["progress"],
        "output_url": None,
        "kind": job.get("kind", "render"),
    }


def _publish(job_id: str, event: dict) -> None:
    for q in list(_subscribers.get(job_id, ())):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # 订阅者太慢则丢弃该事件,下一条会跟上


# ---------- worker ----------

async def _process_job(job_id: str) -> None:
    """处理单个任务:任何异常都落到 failed 状态,不影响 worker 循环。

    ⚠️ 原 2025-Q3 版本会按 kind == "tts" 走 tts_service.synthesize()(Qwen3-TTS pipeline);
    当前版本(回退 Qwen3-TTS)已注释掉该分支,只保留 render pipeline。
    """
    job = await db.get_job_async(job_id)
    if job is None:
        return
    user_id: str = job["user_id"]
    session_id: str = job["session_id"]
    kind: str = job.get("kind", "render")
    try:
        logger.info(
            "Worker picked up %s kind=%s (user=%s session=%s)",
            job_id, kind, user_id, session_id,
        )
        await db.update_job_status_async(job_id, "running", 0)
        _publish(job_id, {"status": "running", "progress": 0, "kind": kind})

        async def progress_cb(percent: int) -> None:
            await db.update_job_status_async(job_id, "running", percent)
            _publish(job_id, {"status": "running", "progress": percent, "kind": kind})

        output_url = f"/api/jobs/{job_id}/output"
        # ⚠️ TTS metadata_json —— Qwen3-TTS(已注释)
        # metadata_json: str | None = None  # noqa: E800 — Qwen3-TTS(已注释)

        if False:  # noqa: E800 — TTS 分支(Qwen3-TTS,已禁用)
            # 以下整段为 Qwen3-TTS 多角色对话合成(2025-Q3,Qwen3-TTS pipeline);
            # 当前版本(回退 Qwen3-TTS)已注释,kind == "tts" 的 job 会落到 else 分支
            # 但 VideoDSL.model_validate 会失败 → 落到 except → fail 状态(预期)。
            # 恢复时把 `if False:` 改成 `if kind == "tts":`,并取消下面 tts_service 调用。
            # wav_path = await tts_service.synthesize(
            #     job_id=job_id,
            #     user_id=user_id,
            #     session_id=session_id,
            #     config=job["config"],
            #     progress_cb=progress_cb,
            # )
            # meta_path = wav_path.with_name(f"{wav_path.stem}.meta.json")
            # if meta_path.is_file():
            #     metadata_json = meta_path.read_text(encoding="utf-8")
            #     meta_path.unlink(missing_ok=True)
            pass
        else:
            dsl = VideoDSL.model_validate(job["config"])
            if dsl.transparent:
                fmt = dsl.transparent_format or "webm_vp9_alpha"
                await recorder.render_video_transparent(
                    dsl=dsl,
                    job_id=job_id,
                    user_id=user_id,
                    session_id=session_id,
                    progress_callback=progress_cb,
                    format=fmt,
                )
            else:
                await recorder.render_video(
                    dsl=dsl,
                    job_id=job_id,
                    user_id=user_id,
                    session_id=session_id,
                    progress_callback=progress_cb,
                )

        # ⚠️ TTS pipeline(已禁用)原本会把 metadata_json 透传给 finish_job;
        # 当前版本不再带 metadata_json。
        await db.finish_job_async(job_id, "done", None)
        tl = timeline_path(user_id, session_id, job_id)
        timeline_url = f"/api/jobs/{job_id}/timeline" if tl.is_file() else None
        # SSE done 事件:重新读一次 job 让 metadata_json 走 db 的 json.loads 路径,
        # 避免这里再手工解析一次(也保证 _publish 出去的形态与 current_event 一致)。
        # ⚠️ 当前版本 metadata_json 永远 None,保留注释方便恢复 Qwen3-TTS。
        done_job = await db.get_job_async(job_id)
        _publish(job_id, {
            "status": "done",
            "progress": 100,
            "output_url": output_url,
            "output_ext": job.get("output_ext"),
            "timeline_url": timeline_url,
            "kind": kind,
            # "metadata_json": (done_job or {}).get("metadata_json"),  # noqa: E800 — Qwen3-TTS(已注释)
        })
        logger.info("Job %s done (kind=%s)", job_id, kind)
    except Exception as exc:  # noqa: BLE001 — worker 异常不导致进程退出
        await db.finish_job_async(job_id, "failed", str(exc))
        _publish(job_id, {
            "status": "failed",
            "progress": 0,
            "error": str(exc),
            "kind": kind,
        })
        logger.exception("Job %s failed: %s", job_id, exc)


async def _worker(name: str) -> None:
    while True:
        job_id = await _queue.get()
        try:
            await _process_job(job_id)
        finally:
            _queue.task_done()


async def _rehydrate_jobs() -> None:
    """启动时:把上次未终态的任务重新塞回队列,保证重启可恢复。"""
    import sqlite3

    # 这里直接走同步 sqlite 拿 id 列表,简单可靠
    conn = sqlite3.connect(str(db.DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id FROM jobs WHERE status IN ('queued', 'running')"
        ).fetchall()
    finally:
        conn.close()
    for r in rows:
        try:
            _queue.put_nowait(r["id"])
        except asyncio.QueueFull:
            logger.warning("Rehydrate queue full, dropping %s", r["id"])
        else:
            # 之前如果是 running 状态,这里降级回 queued,避免中间态被打断后无限 running
            await db.update_job_status_async(r["id"], "queued", 0)
    if rows:
        logger.info("Rehydrated %d in-flight jobs", len(rows))


@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan:启动/关闭 worker 池。"""
    await db.init_schema_async()
    await _rehydrate_jobs()
    workers = [
        asyncio.create_task(_worker(f"worker-{i}")) for i in range(WORKER_COUNT)
    ]
    logger.info("Started %d workers (max queue %d)", WORKER_COUNT, MAX_QUEUE_SIZE)
    try:
        yield
    finally:
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)