"""队列/worker 行为测试 — 对应 docs/06-acceptance.md CODE-1。

jobs 已迁到 SQLite,所以每个用例用 tmp_path 隔离一份 DB,避免污染。
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest

from app import db, queue
from app.dsl import ChatScene, VideoDSL
from app.models import Message, Participant


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """每个用例前把 DB 路径指到 tmp_path,init 一次 schema。"""
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_schema()
    # queue 是模块级,清掉它的内存状态
    queue._subscribers.clear()
    queue._queue = asyncio.Queue(maxsize=queue.MAX_QUEUE_SIZE)
    yield


def make_dsl(**overrides) -> VideoDSL:
    scene = dict(
        participants=[
            Participant(id="a", name="A"),
            Participant(id="b", name="B"),
        ],
        messages=[Message(sender_id="a", kind="text", text="你好", delay_ms=1500)],
    )
    scene.update(overrides)
    return VideoDSL(scene=ChatScene(**scene))


async def _enqueue_test_job(user_id: str = "u-test", session_id: str | None = None) -> str:
    """入队 + 注册 session/user 的便捷函数。"""
    sid = session_id or f"s-{uuid.uuid4().hex[:10]}"
    await db.upsert_user_async(user_id)
    sess = await db.create_session_async(user_id, sid)
    dsl = make_dsl()
    return await queue.enqueue(dsl, sess["id"], user_id)


@pytest.mark.asyncio
async def test_enqueue_and_status():
    """入队 → status 可见,字段齐。"""
    job_id = await _enqueue_test_job()
    status = await queue.get_job_status(job_id, user_id="u-test")
    assert status is not None
    assert status["status"] == "queued"
    assert status["progress"] == 0
    assert status["output_url"] is None  # 未 done 之前不应有 output_url
    assert status["error"] is None
    # 别的用户看不到(等同 404)
    assert await queue.get_job_status(job_id, user_id="other") is None
    # 不传 user_id 也能拿到(给内部用),但返回路径只对本人有效
    raw = await queue.get_job_status(job_id)
    assert raw is not None


@pytest.mark.asyncio
async def test_queue_full_raises():
    """队列满时入队抛 QueueFullError(接口层转 503)。"""
    user_id = "u-test"
    await db.upsert_user_async(user_id)
    sess = await db.create_session_async(user_id, "s-test")

    queue._queue = asyncio.Queue(maxsize=2)
    await queue.enqueue(make_dsl(), sess["id"], user_id)
    await queue.enqueue(make_dsl(), sess["id"], user_id)
    with pytest.raises(queue.QueueFullError):
        await queue.enqueue(make_dsl(), sess["id"], user_id)


@pytest.mark.asyncio
async def test_worker_success_path(monkeypatch):
    """✅ worker 正常流程:done + output_url + 进度回调被调用。"""
    calls: list[int] = []

    async def fake_render(dsl, job_id, user_id, session_id, progress_callback, user=None):
        await progress_callback(30)
        await progress_callback(70)
        # 模拟产物落盘(避免 serve_output 路径检查失败)
        from app.storage import output_path, OUTPUT_EXT
        p = output_path(user_id, session_id, job_id, OUTPUT_EXT)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fake mp4")
        return p

    monkeypatch.setattr(queue.recorder, "render_video", fake_render)

    job_id = await _enqueue_test_job()
    await queue._process_job(job_id)

    status = await queue.get_job_status(job_id, user_id="u-test")
    assert status["status"] == "done"
    assert status["progress"] == 100
    assert status["output_url"] == f"/api/jobs/{job_id}/output"
    assert status["finished_at"] is not None


@pytest.mark.asyncio
async def test_worker_failure_does_not_crash(monkeypatch):
    """✅ recorder 抛异常 → 任务 failed,worker 循环不受影响。"""
    async def boom(dsl, job_id, user_id, session_id, progress_callback, user=None):
        raise RuntimeError("simulated ffmpeg crash")

    monkeypatch.setattr(queue.recorder, "render_video", boom)

    job_id = await _enqueue_test_job()
    await queue._process_job(job_id)  # 不应向外抛异常

    status = await queue.get_job_status(job_id, user_id="u-test")
    assert status["status"] == "failed"
    assert status["progress"] == 0
    assert "simulated ffmpeg crash" in (status["error"] or "")
    assert status["finished_at"] is not None

    # worker 还能继续处理下一个任务
    async def ok(dsl, job_id, user_id, session_id, progress_callback, user=None):
        from app.storage import output_path, OUTPUT_EXT
        p = output_path(user_id, session_id, job_id, OUTPUT_EXT)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    monkeypatch.setattr(queue.recorder, "render_video", ok)
    job2 = await _enqueue_test_job()
    await queue._process_job(job2)
    s2 = await queue.get_job_status(job2, user_id="u-test")
    assert s2["status"] == "done"


@pytest.mark.asyncio
async def test_subscribe_publish_and_current_event():
    """SSE 订阅/发布/当前状态快照。"""
    job_id = await _enqueue_test_job()
    job = await db.get_job_async(job_id)
    q = queue.subscribe(job_id)

    await db.update_job_status_async(job_id, "running", 42)
    queue._publish(job_id, {"status": "running", "progress": 42})
    event = await asyncio.wait_for(q.get(), timeout=1)
    assert event == {"status": "running", "progress": 42}

    ev = await queue.current_event({
        "id": job["id"], "status": "running", "progress": 42,
        "error": None, "output_url": None,
    })
    assert ev["status"] == "running" and ev["progress"] == 42

    queue.unsubscribe(job_id, q)
    assert queue._subscribers.get(job_id) in (None, [])