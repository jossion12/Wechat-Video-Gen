"""队列/worker 行为测试 — 对应 docs/06-acceptance.md CODE-1。"""

from __future__ import annotations

import asyncio

import pytest

from app import queue
from app.models import ChatConfig, Message, Participant


def make_cfg(**overrides) -> ChatConfig:
    cfg = dict(
        participants=[
            Participant(id="a", name="A"),
            Participant(id="b", name="B"),
        ],
        messages=[Message(sender_id="a", kind="text", text="你好", delay_ms=1500)],
    )
    cfg.update(overrides)
    return ChatConfig(**cfg)


@pytest.fixture(autouse=True)
def reset_queue():
    """每个用例前重置模块级队列状态。"""
    queue._jobs.clear()
    queue._queue = asyncio.Queue(maxsize=queue.MAX_QUEUE_SIZE)
    queue._subscribers.clear()
    yield


def test_enqueue_and_status():
    """入队 → queued 状态可见,status 结构正确。"""
    job_id = queue.enqueue(make_cfg())
    assert job_id
    status = queue.get_job_status(job_id)
    assert status is not None
    assert status.status == "queued"
    assert status.progress == 0
    assert status.output_url is None
    assert status.error is None
    assert queue.get_job_status("nope") is None


def test_queue_full_raises():
    """队列满时入队抛 QueueFullError(接口层转 503)。"""
    queue._queue = asyncio.Queue(maxsize=2)
    queue.enqueue(make_cfg())
    queue.enqueue(make_cfg())
    with pytest.raises(queue.QueueFullError):
        queue.enqueue(make_cfg())


def test_worker_success_path(monkeypatch):
    """✅ worker 正常流程:done 状态 + output_url + 进度回调被调用。"""
    calls: list[int] = []

    async def fake_render(config, job_id, cb):
        await cb(30)
        await cb(70)
        return None

    monkeypatch.setattr(queue.recorder, "render_chat", fake_render)

    job_id = queue.enqueue(make_cfg())
    asyncio.run(queue._process_job(job_id))
    status = queue.get_job_status(job_id)
    assert status is not None
    assert status.status == "done"
    assert status.progress == 100
    assert status.output_url == f"/outputs/{job_id}.mp4"
    assert status.finished_at is not None


def test_worker_failure_does_not_crash(monkeypatch):
    """✅ recorder 抛异常 → 任务 failed,worker 循环不受影响(进程不退出)。"""
    async def boom(config, job_id, cb):
        raise RuntimeError("simulated ffmpeg crash")

    monkeypatch.setattr(queue.recorder, "render_chat", boom)

    job_id = queue.enqueue(make_cfg())
    asyncio.run(queue._process_job(job_id))  # 不应向外抛异常
    status = queue.get_job_status(job_id)
    assert status is not None
    assert status.status == "failed"
    assert status.progress == 0
    assert "simulated ffmpeg crash" in (status.error or "")
    assert status.finished_at is not None

    # worker 还能继续处理下一个任务
    async def ok(config, job_id, cb):
        return None

    monkeypatch.setattr(queue.recorder, "render_chat", ok)
    job2 = queue.enqueue(make_cfg())
    asyncio.run(queue._process_job(job2))
    assert queue.get_job_status(job2).status == "done"


def test_subscribe_publish_and_current_event():
    """SSE 订阅/发布/当前状态快照。"""
    job_id = queue.enqueue(make_cfg())
    job = queue.get_job(job_id)
    q = queue.subscribe(job_id)

    job.status = "running"
    job.progress = 42
    queue._publish(job_id, {"status": "running", "progress": 42})
    event = asyncio.run(q.get())
    assert event == {"status": "running", "progress": 42}

    ev = queue.current_event(job)
    assert ev["status"] == "running" and ev["progress"] == 42

    queue.unsubscribe(job_id, q)
    assert queue._subscribers.get(job_id) in (None, [])
