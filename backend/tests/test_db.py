"""DB 层测试 — 用户 / session / file / job CRUD + 跨用户隔离。"""

from __future__ import annotations

import asyncio

import pytest

from app import db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_schema()
    yield


@pytest.mark.asyncio
async def test_upsert_user_creates_then_returns():
    """首次出现自动建,重复调用同 id 不报错并返回已有行。"""
    a = await db.upsert_user_async("u1")
    b = await db.upsert_user_async("u1")
    assert a["id"] == "u1"
    assert a["created_at"] == b["created_at"]


@pytest.mark.asyncio
async def test_session_lifecycle_and_touch():
    """建 session → 取 → touch 改 last_active_at → 列表 → 删。"""
    await db.upsert_user_async("u1")
    s1 = await db.create_session_async("u1", "sess-a", title="测试")
    assert s1["title"] == "测试"
    fetched = await asyncio.to_thread(db.get_session, "sess-a")
    assert fetched is not None
    # touch
    await db.touch_session_async("sess-a")
    touched = await asyncio.to_thread(db.get_session, "sess-a")
    assert touched["last_active_at"] >= s1["last_active_at"]
    # 列表
    rows = await asyncio.to_thread(db.list_user_sessions, "u1")
    assert any(r["id"] == "sess-a" for r in rows)
    # 删
    await db.delete_session_async("sess-a")
    assert await asyncio.to_thread(db.get_session, "sess-a") is None


@pytest.mark.asyncio
async def test_file_insert_and_lookup():
    """file 入库后可按 id / session 取出,跨用户列不出。"""
    await db.upsert_user_async("u1")
    await db.upsert_user_async("u2")
    await db.create_session_async("u1", "s1")
    await db.create_session_async("u2", "s2")
    f1 = await db.insert_file_async(
        file_id="f1", session_id="s1", user_id="u1",
        kind="image", ext="png", size=100, content_type="image/png",
    )
    assert f1["id"] == "f1"
    fetched = await asyncio.to_thread(db.get_file, "f1")
    assert fetched["user_id"] == "u1"
    # 列 session 文件
    files = await asyncio.to_thread(db.list_session_files, "s1")
    assert any(r["id"] == "f1" for r in files)
    files_u2 = await asyncio.to_thread(db.list_session_files, "s2")
    assert files_u2 == []
    # 删
    await asyncio.to_thread(db.delete_file, "f1")
    assert await asyncio.to_thread(db.get_file, "f1") is None


@pytest.mark.asyncio
async def test_job_insert_and_status_progression():
    """job 入库 → 推进状态 → finish。"""
    await db.upsert_user_async("u1")
    await db.create_session_async("u1", "s1")
    config = {"schema_version": "1.0", "kind": "chat", "template": "wechat", "scene": {}}
    j = await db.insert_job_async(
        job_id="j1", session_id="s1", user_id="u1", config=config,
    )
    assert j["status"] == "queued"
    await db.update_job_status_async("j1", "running", 50)
    row = await db.get_job_async("j1")
    assert row["status"] == "running" and row["progress"] == 50
    await db.finish_job_async("j1", "done")
    row = await db.get_job_async("j1")
    assert row["status"] == "done" and row["progress"] == 100
    assert row["finished_at"] is not None


@pytest.mark.asyncio
async def test_jobs_isolated_per_user():
    """jobs 列按 user_id 过滤,跨用户看不到。"""
    await db.upsert_user_async("u1")
    await db.upsert_user_async("u2")
    await db.create_session_async("u1", "s1")
    await db.create_session_async("u2", "s2")
    cfg = {"schema_version": "1.0", "kind": "chat", "template": "wechat", "scene": {}}
    await db.insert_job_async(job_id="j1", session_id="s1", user_id="u1", config=cfg)
    await db.insert_job_async(job_id="j2", session_id="s2", user_id="u2", config=cfg)
    u1_jobs = await asyncio.to_thread(db.list_user_jobs, "u1")
    u2_jobs = await asyncio.to_thread(db.list_user_jobs, "u2")
    assert {j["id"] for j in u1_jobs} == {"j1"}
    assert {j["id"] for j in u2_jobs} == {"j2"}