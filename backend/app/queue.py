"""asyncio 任务队列 + worker 池 — 见 docs/01-architecture.md §D2。

任务状态保存在内存字典 `jobs` 中;worker 数由 WORKER_COUNT 控制;
队列满时入队抛 QueueFullError,上层转 503。SSE 通过每任务订阅队列推送事件。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from app import recorder
from app.models import ChatConfig, Job, JobStatus

logger = logging.getLogger("queue")

WORKER_COUNT = int(os.getenv("WORKER_COUNT", "2"))
MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", "100"))


class QueueFullError(Exception):
    """队列已满。"""


_jobs: dict[str, Job] = {}
_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
_subscribers: dict[str, list[asyncio.Queue]] = {}


# ---------- 对外接口 ----------

def enqueue(config: ChatConfig) -> str:
    """入队并返回 job_id;队列满抛 QueueFullError。"""
    if _queue.full():
        raise QueueFullError("queue is full")
    job_id = uuid.uuid4().hex
    job = Job(id=job_id, config=config)
    _jobs[job_id] = job
    _queue.put_nowait(job_id)
    logger.info("Job %s queued", job_id)
    return job_id


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def get_job_status(job_id: str) -> JobStatus | None:
    job = _jobs.get(job_id)
    if job is None:
        return None
    return JobStatus(
        id=job.id,
        status=job.status,
        progress=job.progress,
        output_url=job.output_url,
        error=job.error,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


def queue_size() -> int:
    return _queue.qsize()


def current_event(job: Job) -> dict:
    """SSE 初始快照 / 最终状态事件。"""
    if job.status == "failed":
        return {"status": "failed", "progress": 0, "error": job.error}
    return {
        "status": job.status,
        "progress": job.progress,
        "output_url": job.output_url,
    }


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


def _publish(job_id: str, event: dict) -> None:
    for q in list(_subscribers.get(job_id, ())):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # 订阅者太慢则丢弃该事件,下一条会跟上


# ---------- worker ----------

async def _process_job(job_id: str) -> None:
    """处理单个任务:任何异常都落到 failed 状态,不影响 worker 循环。"""
    job = _jobs.get(job_id)
    if job is None:
        return
    try:
        logger.info("Worker picked up %s", job_id)
        job.status = "running"
        job.progress = 0
        _publish(job_id, {"status": "running", "progress": 0})

        async def progress_cb(percent: int) -> None:
            job.progress = percent
            _publish(job_id, {"status": "running", "progress": percent})

        await recorder.render_chat(job.config, job_id, progress_cb)

        job.status = "done"
        job.progress = 100
        job.output_url = f"/outputs/{job_id}.mp4"
        job.finished_at = time.time()
        _publish(
            job_id,
            {"status": "done", "progress": 100, "output_url": job.output_url},
        )
        logger.info("Job %s done", job_id)
    except Exception as exc:  # noqa: BLE001 — worker 异常不导致进程退出
        job.status = "failed"
        job.progress = 0
        job.error = str(exc)
        job.finished_at = time.time()
        _publish(job_id, {"status": "failed", "progress": 0, "error": str(exc)})
        logger.exception("Job %s failed: %s", job_id, exc)


async def _worker(name: str) -> None:
    while True:
        job_id = await _queue.get()
        try:
            await _process_job(job_id)
        finally:
            _queue.task_done()


@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan:启动/关闭 worker 池。"""
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
