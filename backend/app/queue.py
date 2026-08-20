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
from app.dsl import VideoDSL

logger = logging.getLogger("queue")

WORKER_COUNT = int(os.getenv("WORKER_COUNT", "2"))
MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", "100"))


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
    await db.insert_job_async(
        job_id=job_id,
        session_id=session_id,
        user_id=user_id,
        config=config,
    )
    await db.touch_session_async(session_id)
    _queue.put_nowait(job_id)
    logger.info("Job %s queued (user=%s session=%s)", job_id, user_id, session_id)
    return job_id


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
    else:
        out = None
    return {
        "id": job["id"],
        "status": job["status"],
        "progress": job["progress"],
        "output_url": out,
        "error": job["error"],
        "created_at": job["created_at"],
        "finished_at": job["finished_at"],
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
        return {"status": "failed", "progress": 0, "error": job.get("error")}
    if job["status"] == "done":
        return {
            "status": "done",
            "progress": 100,
            "output_url": job.get("output_url") or f"/api/jobs/{job['id']}/output",
        }
    return {"status": job["status"], "progress": job["progress"], "output_url": None}


def _publish(job_id: str, event: dict) -> None:
    for q in list(_subscribers.get(job_id, ())):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # 订阅者太慢则丢弃该事件,下一条会跟上


# ---------- worker ----------

async def _process_job(job_id: str) -> None:
    """处理单个任务:任何异常都落到 failed 状态,不影响 worker 循环。"""
    job = await db.get_job_async(job_id)
    if job is None:
        return
    user_id: str = job["user_id"]
    session_id: str = job["session_id"]
    try:
        logger.info("Worker picked up %s (user=%s session=%s)", job_id, user_id, session_id)
        await db.update_job_status_async(job_id, "running", 0)
        _publish(job_id, {"status": "running", "progress": 0})

        dsl = VideoDSL.model_validate(job["config"])

        async def progress_cb(percent: int) -> None:
            await db.update_job_status_async(job_id, "running", percent)
            _publish(job_id, {"status": "running", "progress": percent})

        await recorder.render_video(
            dsl=dsl,
            job_id=job_id,
            user_id=user_id,
            session_id=session_id,
            progress_callback=progress_cb,
        )

        output_url = f"/api/jobs/{job_id}/output"
        await db.finish_job_async(job_id, "done", None)
        _publish(job_id, {"status": "done", "progress": 100, "output_url": output_url})
        logger.info("Job %s done", job_id)
    except Exception as exc:  # noqa: BLE001 — worker 异常不导致进程退出
        await db.finish_job_async(job_id, "failed", str(exc))
        _publish(job_id, {"status": "failed", "progress": 0, "error": str(exc)})
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