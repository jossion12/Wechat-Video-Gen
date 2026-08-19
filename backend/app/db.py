"""SQLite 数据访问层 — 用户 / session / 文件 / 任务 全在库里。

设计目标:
- 单文件 SQLite,放 STORAGE_DIR 下的 wechat-video-gen.db,WAL 模式避免锁竞争。
- 所有表的主键都是 26 位 ulid-like(实际用 uuid4().hex,26 字符的子串)便于 URL 用。
- 每个写操作是同步 sqlite3 调用;从 async 代码调用时通过 asyncio.to_thread() 包装。
- 不引第三方 ORM,直接用 sqlite3,避免依赖膨胀。
- schema 在 init_schema() 里启动时一次性建好。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from app.storage import STORAGE_DIR

logger = logging.getLogger("db")

DB_PATH = STORAGE_DIR / "wechat-video-gen.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# 全局写锁 — sqlite3 单进程串行写没问题,但跨线程并发写会卡;
# 用一个进程级互斥锁兜底,避开 "database is locked"。
_write_lock = threading.Lock()

# ---------- schema ----------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    title           TEXT,
    created_at      REAL NOT NULL,
    last_active_at  REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, last_active_at DESC);

CREATE TABLE IF NOT EXISTS files (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    kind         TEXT NOT NULL,
    ext          TEXT NOT NULL,
    size         INTEGER NOT NULL,
    content_type TEXT,
    created_at   REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (user_id)    REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_files_session ON files(session_id);
CREATE INDEX IF NOT EXISTS idx_files_user    ON files(user_id);

CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    status       TEXT NOT NULL,
    progress     INTEGER NOT NULL DEFAULT 0,
    config_json  TEXT NOT NULL,
    output_ext   TEXT NOT NULL DEFAULT 'mp4',
    error        TEXT,
    created_at   REAL NOT NULL,
    finished_at  REAL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (user_id)    REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_user    ON jobs(user_id, created_at DESC);
"""


def _connect() -> sqlite3.Connection:
    """每次新建连接,保证线程安全(FastAPI sync route 在 threadpool 里跑)。

    isolation_level=""(默认)让 python sqlite3 使用隐式 BEGIN/COMMIT 管理事务,
    _cursor() 里的显式 BEGIN 让多语句操作真正原子(autocommit 模式下 conn.commit() 是 no-op)。
    """
    conn = sqlite3.connect(
        str(DB_PATH),
        timeout=10.0,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _cursor() -> Iterator[sqlite3.Cursor]:
    """拿一个连接 + 游标,出错自动回滚,正常提交。

    每个上下文都是一条独立事务;多语句操作(BEGIN/COMMIT)与单语句都走同一路径,
    避免「isolation_level=None 下 commit 是 no-op」的坑。
    """
    with _write_lock:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")
            try:
                yield cur
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
        finally:
            conn.close()


def init_schema() -> None:
    """应用启动时调一次,创建所有表(IF NOT EXISTS,幂等)。

    DDL不走 _cursor():sqlite3 Cursor.executescript() 会自己隐式 COMMIT,
    与 _cursor 里的显式 BEGIN..COMMIT 会打架(后面 commit 时报 no transaction)。
    """
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    logger.info("DB schema ready at %s", DB_PATH)


async def init_schema_async() -> None:
    """异步入口,worker 启动时调一次。"""
    await asyncio.to_thread(init_schema)


# ---------- users ----------

def upsert_user(user_id: str, username: str | None = None) -> dict:
    """首次出现的 user 自动入库;username 缺失则用 user_id 当 username。

    Returns: dict(id, username, created_at) — 二次调用同 id 返回完全相同的 created_at。
    """
    name = username or user_id
    with _cursor() as cur:
        cur.execute("SELECT id, username, created_at FROM users WHERE id=?", (user_id,))
        row = cur.fetchone()
        if row is None:
            ts = time.time()
            cur.execute(
                "INSERT INTO users(id, username, created_at) VALUES (?, ?, ?)",
                (user_id, name, ts),
            )
            return {"id": user_id, "username": name, "created_at": ts}
        return dict(row)


async def upsert_user_async(user_id: str, username: str | None = None) -> dict:
    return await asyncio.to_thread(upsert_user, user_id, username)


def get_user(user_id: str) -> dict | None:
    with _cursor() as cur:
        cur.execute("SELECT id, username, created_at FROM users WHERE id=?", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


# ---------- sessions ----------

def create_session(user_id: str, session_id: str, title: str | None = None) -> dict:
    now = time.time()
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO sessions(id, user_id, title, created_at, last_active_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, title, now, now),
        )
    return {
        "id": session_id,
        "user_id": user_id,
        "title": title,
        "created_at": now,
        "last_active_at": now,
    }


async def create_session_async(user_id: str, session_id: str, title: str | None = None) -> dict:
    return await asyncio.to_thread(create_session, user_id, session_id, title)


def get_session(session_id: str) -> dict | None:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, user_id, title, created_at, last_active_at "
            "FROM sessions WHERE id=?",
            (session_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def list_user_sessions(user_id: str, limit: int = 100) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, user_id, title, created_at, last_active_at "
            "FROM sessions WHERE user_id=? ORDER BY last_active_at DESC LIMIT ?",
            (user_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def touch_session(session_id: str) -> None:
    """session 活跃时刷新 last_active_at。"""
    with _cursor() as cur:
        cur.execute(
            "UPDATE sessions SET last_active_at=? WHERE id=?",
            (time.time(), session_id),
        )


async def touch_session_async(session_id: str) -> None:
    await asyncio.to_thread(touch_session, session_id)


def delete_session(session_id: str) -> None:
    """删 session 行;cascade 不开,文件/任务靠应用层删(见 storage.py / queue.py)。"""
    with _cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE id=?", (session_id,))


async def delete_session_async(session_id: str) -> None:
    await asyncio.to_thread(delete_session, session_id)


def delete_session_cascade(session_id: str) -> dict[str, int]:
    """一个事务里删掉 session 及其下属 files / jobs 行。

    Returns: {"files": n, "jobs": m, "sessions": k} 表示各表删除的行数。

    调用顺序要求 — DB 先动,磁盘后动:
      deleted = delete_session_cascade(sid)   # 原子;失败则磁盘不动
      remove_session(user_id, sid)            # 全部清理;失败也仅是多占点磁盘
    """
    with _cursor() as cur:
        cur.execute("DELETE FROM files  WHERE session_id=?", (session_id,))
        n_files = cur.rowcount
        cur.execute("DELETE FROM jobs   WHERE session_id=?", (session_id,))
        n_jobs = cur.rowcount
        cur.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        n_sess = cur.rowcount
    return {"files": n_files, "jobs": n_jobs, "sessions": n_sess}


async def delete_session_cascade_async(session_id: str) -> dict[str, int]:
    return await asyncio.to_thread(delete_session_cascade, session_id)


# ---------- files ----------

def insert_file(
    file_id: str,
    session_id: str,
    user_id: str,
    kind: str,
    ext: str,
    size: int,
    content_type: str | None,
) -> dict:
    now = time.time()
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO files(id, session_id, user_id, kind, ext, size, content_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (file_id, session_id, user_id, kind, ext, size, content_type, now),
        )
    return {
        "id": file_id,
        "session_id": session_id,
        "user_id": user_id,
        "kind": kind,
        "ext": ext,
        "size": size,
        "content_type": content_type,
        "created_at": now,
    }


async def insert_file_async(**kwargs: Any) -> dict:
    return await asyncio.to_thread(insert_file, **kwargs)


def get_file(file_id: str) -> dict | None:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, session_id, user_id, kind, ext, size, content_type, created_at "
            "FROM files WHERE id=?",
            (file_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def list_session_files(session_id: str) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, session_id, user_id, kind, ext, size, content_type, created_at "
            "FROM files WHERE session_id=? ORDER BY created_at ASC",
            (session_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def delete_file(file_id: str) -> None:
    with _cursor() as cur:
        cur.execute("DELETE FROM files WHERE id=?", (file_id,))


# ---------- jobs ----------

def insert_job(
    job_id: str,
    session_id: str,
    user_id: str,
    config: dict,
) -> dict:
    now = time.time()
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO jobs(id, session_id, user_id, status, progress, config_json, output_ext, created_at) "
            "VALUES (?, ?, ?, 'queued', 0, ?, 'mp4', ?)",
            (job_id, session_id, user_id, json.dumps(config, ensure_ascii=False), now),
        )
    return {
        "id": job_id,
        "session_id": session_id,
        "user_id": user_id,
        "status": "queued",
        "progress": 0,
        "config_json": config,
        "output_ext": "mp4",
        "error": None,
        "created_at": now,
        "finished_at": None,
    }


async def insert_job_async(**kwargs: Any) -> dict:
    return await asyncio.to_thread(insert_job, **kwargs)


def get_job(job_id: str) -> dict | None:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, session_id, user_id, status, progress, config_json, output_ext, error, created_at, finished_at "
            "FROM jobs WHERE id=?",
            (job_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        # config_json 解码方便上层用
        try:
            d["config"] = json.loads(d.pop("config_json") or "{}")
        except Exception:  # noqa: BLE001 — 损坏的 JSON 也照常返回 row
            d["config"] = {}
        return d


async def get_job_async(job_id: str) -> dict | None:
    return await asyncio.to_thread(get_job, job_id)


def update_job_status(job_id: str, status: str, progress: int | None = None) -> None:
    with _cursor() as cur:
        if progress is None:
            cur.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
        else:
            cur.execute(
                "UPDATE jobs SET status=?, progress=? WHERE id=?",
                (status, progress, job_id),
            )


def finish_job(job_id: str, status: str, error: str | None = None) -> None:
    with _cursor() as cur:
        cur.execute(
            "UPDATE jobs SET status=?, progress=?, error=?, finished_at=? WHERE id=?",
            (status, 100 if status == "done" else 0, error, time.time(), job_id),
        )


async def finish_job_async(job_id: str, status: str, error: str | None = None) -> None:
    await asyncio.to_thread(finish_job, job_id, status, error)


async def update_job_status_async(
    job_id: str, status: str, progress: int | None = None
) -> None:
    await asyncio.to_thread(update_job_status, job_id, status, progress)


def list_session_jobs(session_id: str, limit: int = 50) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, session_id, user_id, status, progress, output_ext, error, created_at, finished_at "
            "FROM jobs WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def list_user_jobs(user_id: str, limit: int = 50) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, session_id, user_id, status, progress, output_ext, error, created_at, finished_at "
            "FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def count_by_status(job_ids: Iterable[str]) -> dict[str, int]:
    """统计一组 job_id 的状态分布(健康检查用)。"""
    ids = list(job_ids)
    if not ids:
        return {}
    with _cursor() as cur:
        placeholders = ",".join("?" * len(ids))
        cur.execute(
            f"SELECT status, COUNT(*) AS n FROM jobs WHERE id IN ({placeholders}) GROUP BY status",
            ids,
        )
        return {r["status"]: r["n"] for r in cur.fetchall()}