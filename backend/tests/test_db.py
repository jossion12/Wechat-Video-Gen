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
    config = {"schema_version": "1.0", "kind": "chat", "template": "cyberpunk", "scene": {}}
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
    cfg = {"schema_version": "1.0", "kind": "chat", "template": "cyberpunk", "scene": {}}
    await db.insert_job_async(job_id="j1", session_id="s1", user_id="u1", config=cfg)
    await db.insert_job_async(job_id="j2", session_id="s2", user_id="u2", config=cfg)
    u1_jobs = await asyncio.to_thread(db.list_user_jobs, "u1")
    u2_jobs = await asyncio.to_thread(db.list_user_jobs, "u2")
    assert {j["id"] for j in u1_jobs} == {"j1"}
    assert {j["id"] for j in u2_jobs} == {"j2"}


def test_ensure_columns_adds_output_ext_to_existing_jobs_table(tmp_path, monkeypatch):
    """✅ 升级路径:已有 jobs 表(无 output_ext)必须被迁移到带 output_ext。

    不修这条路径的话,所有升级过 SCHEMA 但还跑旧 CREATE TABLE 的部署,首次
    INSERT 会 `sqlite3.OperationalError: no such column: output_ext` 炸 500。

    步骤:
      1) 用旧 schema 手工建 jobs 表(不带 output_ext),模拟升级前的现场。
      2) 调一次 db.init_schema() 模拟启动时的迁移路径。
      3) insert_job(output_ext="webm") 必须成功;get_job 读出来的 output_ext 也要对得上。
    """
    import sqlite3

    test_db = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)

    # 1) 旧 schema —— jobs 表不带 output_ext 列,模拟升级前的线上状态。
    legacy = sqlite3.connect(str(test_db))
    try:
        legacy.executescript(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                created_at REAL NOT NULL
            );
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT,
                created_at REAL NOT NULL,
                last_active_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE files (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                ext TEXT NOT NULL,
                size INTEGER NOT NULL,
                content_type TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                FOREIGN KEY (user_id)    REFERENCES users(id)
            );
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                config_json TEXT NOT NULL,
                -- 注意:这里没有 output_ext 列
                error TEXT,
                created_at REAL NOT NULL,
                finished_at REAL,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                FOREIGN KEY (user_id)    REFERENCES users(id)
            );
            """
        )
        legacy.commit()
    finally:
        legacy.close()

    # 2) 模拟启动 → _ensure_columns 必须把 output_ext 加回去。
    db.init_schema()

    # 3) 升级后 insert / get 都按新列工作。
    db.upsert_user("u-legacy")
    db.create_session("u-legacy", "s-legacy")
    config = {
        "schema_version": "1.0", "kind": "chat", "template": "cyberpunk",
        "transparent": True, "transparent_format": "webm_vp9_alpha",
        "scene": {},
    }
    db.insert_job(
        job_id="j-legacy", session_id="s-legacy", user_id="u-legacy",
        config=config, output_ext="webm",
    )
    row = db.get_job("j-legacy")
    assert row is not None
    assert row["output_ext"] == "webm"

    # 顺手验:迁移后没指定 output_ext 的旧代码路径仍然能跑(默认 mp4)。
    db.insert_job(
        job_id="j-legacy-mp4", session_id="s-legacy", user_id="u-legacy",
        config=config,
    )
    assert db.get_job("j-legacy-mp4")["output_ext"] == "mp4"