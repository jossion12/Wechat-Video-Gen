"""SQLite 数据访问层 — 用户 / session / 文件 / 任务 全在库里。

设计目标:
- 单文件 SQLite,放 STORAGE_DIR 下的 dialogue-theater.db,WAL 模式避免锁竞争。
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

DB_PATH = STORAGE_DIR / "dialogue-theater.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# 全局写锁 — sqlite3 单进程串行写没问题,但跨线程并发写会卡;
# 用一个进程级互斥锁兜底,避开 "database is locked"。
_write_lock = threading.Lock()

# ---------- schema ----------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    created_at      REAL NOT NULL,
    registered_at   REAL,
    paid_at         REAL
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
    md5          TEXT,                       -- 素材去重用(兼容旧数据允许 NULL)
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


def _parse_metadata_json(value: str | None) -> dict | None:
    """⚠️ Qwen3-TTS 单段失败明细解码(已注释)⚠️

    把 jobs.metadata_json TEXT 列解成 dict;空 / 损坏时返回 None。
    当前版本(回退 Qwen3-TTS)此函数不再被调用 —— 见 db.get_job / list_*_jobs /
    find_latest_tts_by_source 已注释对应解码逻辑 —— 保留作为工具函数以便恢复。
    """
    if not value:
        return None
    try:
        loaded = json.loads(value)
    except (TypeError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """向后兼容:对已有表追加后续版本新增的列。

    只增列、不删列、不改类型。SQLite 的 `ALTER TABLE ... ADD COLUMN ... NOT NULL
    DEFAULT 'mp4'` 在已有数据上会回填默认值,等价于"把现存行标成 mp4 产物" —
    升级前入库的旧 job 在升级后仍然会被识别为 mp4,不会丢失。
    """
    existing = {
        r["name"]
        for r in conn.execute(
            "SELECT type, name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "users" in existing:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "registered_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN registered_at REAL")
        if "paid_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN paid_at REAL")
    if "files" in existing:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(files)").fetchall()}
        if "md5" not in cols:
            conn.execute("ALTER TABLE files ADD COLUMN md5 TEXT")
    if "jobs" in existing:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        if "output_ext" not in cols:
            conn.execute(
                "ALTER TABLE jobs ADD COLUMN output_ext TEXT NOT NULL DEFAULT 'mp4'"
            )
        # ⚠️ kind / metadata_json 是 TTS pipeline 引入的(2025-Q3,Qwen3-TTS)。
        # 当前版本(回退 Qwen3-TTS)仍保留这两列:已迁移/已生产数据库里它们已经存在,
        # 移除会导致迁移回退困难。下面两条 ALTER 在已存在列上 no-op,幂等安全。
        # 旧 job 落 'render' + NULL,跟 output_ext 一样的 NOT NULL DEFAULT 兼容迁移。
        if "kind" not in cols:
            conn.execute(
                "ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'render'"
            )
        if "metadata_json" not in cols:
            conn.execute(
                "ALTER TABLE jobs ADD COLUMN metadata_json TEXT"
            )


def init_schema() -> None:
    """应用启动时调一次,创建所有表(IF NOT EXISTS,幂等)。

    DDL不走 _cursor():sqlite3 Cursor.executescript() 会自己隐式 COMMIT,
    与 _cursor 里的显式 BEGIN..COMMIT 会打架(后面 commit 时报 no transaction)。
    """
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        _ensure_columns(conn)
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

    Returns: dict(id, username, created_at, registered_at, paid_at)。
    """
    name = username or user_id
    with _cursor() as cur:
        cur.execute(
            "SELECT id, username, created_at, registered_at, paid_at FROM users WHERE id=?",
            (user_id,),
        )
        row = cur.fetchone()
        if row is None:
            ts = time.time()
            cur.execute(
                "INSERT INTO users(id, username, created_at) VALUES (?, ?, ?)",
                (user_id, name, ts),
            )
            return {
                "id": user_id,
                "username": name,
                "created_at": ts,
                "registered_at": None,
                "paid_at": None,
            }
        return dict(row)


async def upsert_user_async(user_id: str, username: str | None = None) -> dict:
    return await asyncio.to_thread(upsert_user, user_id, username)


def get_user(user_id: str) -> dict | None:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, username, created_at, registered_at, paid_at FROM users WHERE id=?",
            (user_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


async def get_user_async(user_id: str) -> dict | None:
    return await asyncio.to_thread(get_user, user_id)


def mark_user_registered(user_id: str) -> dict:
    """标记用户已注册;已注册则保留原时间。"""
    with _cursor() as cur:
        cur.execute(
            "UPDATE users SET registered_at=COALESCE(registered_at, ?) WHERE id=?",
            (time.time(), user_id),
        )
    return get_user(user_id)


async def mark_user_registered_async(user_id: str) -> dict:
    return await asyncio.to_thread(mark_user_registered, user_id)


def mark_user_paid(user_id: str) -> dict:
    """标记用户已充值/付费;已付费则保留原时间。"""
    with _cursor() as cur:
        cur.execute(
            "UPDATE users SET paid_at=COALESCE(paid_at, ?) WHERE id=?",
            (time.time(), user_id),
        )
    return get_user(user_id)


async def mark_user_paid_async(user_id: str) -> dict:
    return await asyncio.to_thread(mark_user_paid, user_id)


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
    md5: str | None = None,
) -> dict:
    now = time.time()
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO files(id, session_id, user_id, kind, ext, size, content_type, md5, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (file_id, session_id, user_id, kind, ext, size, content_type, md5, now),
        )
    return {
        "id": file_id,
        "session_id": session_id,
        "user_id": user_id,
        "kind": kind,
        "ext": ext,
        "size": size,
        "content_type": content_type,
        "md5": md5,
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
    output_ext: str = "mp4",
    *,
    kind: str = "render",
) -> dict:
    """⚠️ metadata_json 参数(2025-Q3 引入,Qwen3-TTS)已注释 ⚠️

    当前版本(回退 Qwen3-TTS)不再接受 metadata_json 参数。db 层仍保留 jobs 表的
    metadata_json 列(由 _ensure_columns 自动迁移,无破坏性),但 insert 一律落
    NULL,query 一律返回 None。
    """
    # 兜底:防止下游 restore 调用误传 metadata_json。
    # if "metadata_json" in kwargs:  # noqa: E800 — Qwen3-TTS(已注释)
    #     raise TypeError("metadata_json 参数已被注释(Qwen3-TTS,DISABLED);当前版本不接受。")
    now = time.time()
    if output_ext not in ("mp4", "webm", "mov"):
        # ⚠️ "wav" 从白名单移除 —— Qwen3-TTS 产物的扩展名,当前版本注释。
        # 兜底:未知扩展名拒绝入库,避免后续 serve_output 取到非法路径。
        raise ValueError(f"unsupported output_ext: {output_ext!r}")
    if kind not in ("render", "tts"):
        raise ValueError(f"unsupported job kind: {kind!r}")
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO jobs(id, session_id, user_id, status, progress, config_json, "
            "output_ext, kind, metadata_json, created_at) "
            "VALUES (?, ?, ?, 'queued', 0, ?, ?, ?, NULL, ?)",
            (
                job_id,
                session_id,
                user_id,
                json.dumps(config, ensure_ascii=False),
                output_ext,
                kind,
                now,
            ),
        )
    return {
        "id": job_id,
        "session_id": session_id,
        "user_id": user_id,
        "status": "queued",
        "progress": 0,
        "config_json": config,
        "output_ext": output_ext,
        "kind": kind,
        "metadata_json": None,  # ⚠️ Qwen3-TTS(已注释)—— 永远 None
        "error": None,
        "created_at": now,
        "finished_at": None,
    }


async def insert_job_async(**kwargs: Any) -> dict:
    return await asyncio.to_thread(insert_job, **kwargs)


def get_job(job_id: str) -> dict | None:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, session_id, user_id, status, progress, config_json, output_ext, "
            "kind, metadata_json, error, created_at, finished_at "
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
        # ⚠️ metadata_json(Qwen3-TTS)当前版本不再解码,直接置 None。
        # 旧数据库里可能仍有历史值,但已不再被前端/API 消费。
        d.pop("metadata_json", None)
        d["metadata_json"] = None
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


def finish_job(
    job_id: str,
    status: str,
    error: str | None = None,
) -> None:
    """完成任务落库。

    ⚠️ metadata_json 参数(2025-Q3,Qwen3-TTS)已注释 ⚠️
      原 2025-Q3 版本会在这里写入 {"failed_segments": [...]} 用于前端展示;
      当前版本(回退 Qwen3-TTS)不再支持该字段,jobs.metadata_json 列保留但永远 NULL。
    """
    with _cursor() as cur:
        cur.execute(
            "UPDATE jobs SET status=?, progress=?, error=?, finished_at=? WHERE id=?",
            (
                status,
                100 if status == "done" else 0,
                error,
                time.time(),
                job_id,
            ),
        )


async def finish_job_async(
    job_id: str,
    status: str,
    error: str | None = None,
) -> None:
    # ⚠️ metadata_json 参数(Qwen3-TTS)已注释;旧调用方传参会被静默吞掉。
    await asyncio.to_thread(finish_job, job_id, status, error)


async def update_job_status_async(
    job_id: str, status: str, progress: int | None = None
) -> None:
    await asyncio.to_thread(update_job_status, job_id, status, progress)


def list_session_jobs(session_id: str, limit: int = 50) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, session_id, user_id, status, progress, output_ext, kind, "
            "metadata_json, error, created_at, finished_at "
            "FROM jobs WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        # ⚠️ metadata_json(Qwen3-TTS)当前版本不再解码,统一置 None。
        r.pop("metadata_json", None)
        r["metadata_json"] = None
    return rows


def list_user_jobs(user_id: str, limit: int = 50) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, session_id, user_id, status, progress, output_ext, kind, "
            "metadata_json, error, created_at, finished_at "
            "FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        # ⚠️ metadata_json(Qwen3-TTS)当前版本不再解码,统一置 None。
        r.pop("metadata_json", None)
        r["metadata_json"] = None
    return rows


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


def find_latest_tts_by_source(user_id: str, source_job_id: str) -> dict | None:
    """⚠️ Qwen3-TTS 时间码页持久化查询(2025-Q3,DISABLED / DEPRECATED)⚠️

    原用途:查某 user 在 source_job_id 这个 render 任务上最近一个 TTS 子任务
    (用于 GET /api/tts/by-source/{job_id},前端时间码页持久化展示 TTS 状态)。
    当前版本(回退 Qwen3-TTS)直接返回 None;调用方 main.submit_tts_by_source_job
    也已注释(整个 /api/tts/by-source 端点都已 `if False:` 包裹),保留函数签名
    以便恢复。

    没装 SQLite JSON1,所以走 LIKE 字符串匹配。job_id 是 26 位 hex,
    与其它 config_json 字段不会撞("source_job_id":"26hex" 是定长带引号 + 字段名,
    误伤概率接近 0;性能靠 user_id+kind 双重命中 + created_at DESC 限定)。

    注意:json.dumps 默认输出 `"key": "val"`(冒号后有空格),但 insert_job 写库
    时不强制格式,新旧数据可能并存。这里同时匹配两种格式(紧凑 / 带空格),
    保证前后兼容。
    """
    # ⚠️ Qwen3-TTS 集成(2025-Q3,DISABLED / DEPRECATED):
    # 当前版本直接返回 None,保留下方 SQL 供恢复。
    return None
    needle_compact = f'%"source_job_id":"{source_job_id}"%'
    needle_spaced = f'%"source_job_id": "{source_job_id}"%'
    with _cursor() as cur:
        cur.execute(
            "SELECT id, session_id, user_id, status, progress, config_json, output_ext, "
            "kind, metadata_json, error, created_at, finished_at "
            "FROM jobs "
            "WHERE user_id=? AND kind='tts' "
            "AND (config_json LIKE ? OR config_json LIKE ?) "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id, needle_compact, needle_spaced),
        )
        row = cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        try:
            d["config"] = json.loads(d.pop("config_json") or "{}")
        except Exception:  # noqa: BLE001
            d["config"] = {}
        d["metadata_json"] = _parse_metadata_json(d.pop("metadata_json"))
        return d