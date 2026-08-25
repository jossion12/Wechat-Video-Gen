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
        intent="short_video_drama",
        intent_acknowledged=True,
        participants=[
            Participant(id="a", name="A", persona=""),
            Participant(id="b", name="B", persona=""),
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

    async def fake_render(dsl, job_id, user_id, session_id, progress_callback):
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
    async def boom(dsl, job_id, user_id, session_id, progress_callback):
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
    async def ok(dsl, job_id, user_id, session_id, progress_callback):
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
async def test_worker_dispatches_transparent_webm(monkeypatch, tmp_path):
    """✅ dsl.transparent=True + transparent_format='webm_vp9_alpha'
       → 调 render_video_transparent(..., format='webm_vp9_alpha');
       dsl.transparent=False → 调 render_video。
    """
    calls: list[tuple[str, str]] = []

    async def fake_transparent(dsl, job_id, user_id, session_id, progress_callback, *, format):
        calls.append(("transparent", format))
        # 模拟产物落盘
        from app.storage import output_path, OUTPUT_EXT_WEBM_ALPHA
        p = output_path(user_id, session_id, job_id, OUTPUT_EXT_WEBM_ALPHA)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fake webm")
        return p

    async def fake_opaque(dsl, job_id, user_id, session_id, progress_callback):
        calls.append(("opaque", "mp4"))
        from app.storage import output_path, OUTPUT_EXT
        p = output_path(user_id, session_id, job_id, OUTPUT_EXT)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fake mp4")
        return p

    monkeypatch.setattr(queue.recorder, "render_video_transparent", fake_transparent)
    monkeypatch.setattr(queue.recorder, "render_video", fake_opaque)

    # 入队一个透明 webm 任务
    user_id = "u-trans"
    await db.upsert_user_async(user_id)
    sess = await db.create_session_async(user_id, f"s-{user_id}")
    webm_dsl = make_dsl()
    # Pydantic v2:直接 model_copy 改字段
    webm_dsl = webm_dsl.model_copy(update={
        "transparent": True,
        "transparent_format": "webm_vp9_alpha",
    })
    job_webm = await queue.enqueue(webm_dsl, sess["id"], user_id)
    assert (await db.get_job_async(job_webm))["output_ext"] == "webm"
    await queue._process_job(job_webm)

    # 入队一个透明 mov 任务
    mov_dsl = make_dsl().model_copy(update={
        "transparent": True,
        "transparent_format": "mov_prores4444",
    })
    job_mov = await queue.enqueue(mov_dsl, sess["id"], user_id)
    assert (await db.get_job_async(job_mov))["output_ext"] == "mov"
    await queue._process_job(job_mov)

    # 入队一个不透明任务(回归测试)
    opaque_dsl = make_dsl()
    job_opaque = await queue.enqueue(opaque_dsl, sess["id"], user_id)
    assert (await db.get_job_async(job_opaque))["output_ext"] == "mp4"
    await queue._process_job(job_opaque)

    assert calls == [
        ("transparent", "webm_vp9_alpha"),
        ("transparent", "mov_prores4444"),
        ("opaque", "mp4"),
    ]


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