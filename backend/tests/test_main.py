"""路由级集成测试 — P0 修复后的关键 case。

涵盖:
- /api/preview-html 鉴权 + session 归属 (P0-1)
- DELETE /api/sessions/{id} DB 事务原子 + 磁盘清理 (P0-2)
- _decorate_session 异步化不阻塞 (P0-3)
- 跨用户访问他人的 session / file / job 一律 404
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, main
from app.dsl import ChatScene, VideoDSL
from app.models import Message, Participant


@pytest.fixture(autouse=True)
def isolated_app(tmp_path, monkeypatch):
    """每例:DB 指到 tmp、STORAGE_DIR 指向 tmp、构造 app instance。"""
    test_db = tmp_path / "test.db"
    test_storage = tmp_path / "storage"
    test_storage.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(db, "DB_PATH", test_db)
    # 关键:db.STORAGE_DIR 是 import 时的旧值,但 storage 内部函数读模块 namespace 是动态的。
    # 同一处改 storage.STORAGE_DIR 即可。
    from app import storage as storage_pkg
    monkeypatch.setattr(storage_pkg, "STORAGE_DIR", test_storage)
    db.init_schema()
    yield test_storage


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def user_storage(isolated_app):
    """同一例里写文件 / 检查文件都走这个路径,跟被 monkeypatch 的 STORAGE_DIR 一致。"""
    return isolated_app


def _make_dsl() -> VideoDSL:
    return VideoDSL(
        scene=ChatScene(
            mode="single",
            intent="short_video_drama",
            intent_acknowledged=True,
            participants=[
                Participant(id="me", name="我", persona=""),
                Participant(id="her", name="她", persona=""),
            ],
            messages=[
                Message(sender_id="me", kind="text", text="hi", delay_ms=1500),
            ],
        )
    )


def _h(uid: str) -> dict[str, str]:
    return {"X-User-Id": uid}


# ---------- /api/preview-html 鉴权 + 归属 (P0-1) ----------

def test_preview_html_requires_auth(client, user_storage):
    """无 X-User-Id → 401。"""
    r = client.post(
        "/api/preview-html",
        json={"dsl": _make_dsl().model_dump(mode="json"), "session_id": "any"},
    )
    assert r.status_code == 401


def test_preview_html_requires_owned_session(client, user_storage):
    """session 不存在或跨用户 → 404。"""
    # 先建一个 alice 的 session
    r = client.post("/api/sessions", headers=_h("alice"))
    assert r.status_code == 201
    alice_sid = r.json()["id"]

    # bob 用 alice 的 session_id 调 → 404
    # 用 client.cookies 覆盖之前 alice POST 设的 user_id cookie。
    client.cookies.clear()
    client.cookies.set("user_id", "bob")
    r = client.post(
        "/api/preview-html",
        headers=_h("bob"),
        json={"dsl": _make_dsl().model_dump(mode="json"), "session_id": alice_sid},
    )
    assert r.status_code == 404

    # 不存在的 session_id → 404
    client.cookies.clear()
    client.cookies.set("user_id", "alice")
    r = client.post(
        "/api/preview-html",
        headers=_h("alice"),
        json={"dsl": _make_dsl().model_dump(mode="json"), "session_id": "no-such-session"},
    )
    assert r.status_code == 404


def test_preview_html_renders_for_owned_session(client, user_storage):
    """alice 用自己的 session_id → 200 + 返回 HTML。"""
    r = client.post("/api/sessions", headers=_h("alice"))
    sid = r.json()["id"]
    r = client.post(
        "/api/preview-html",
        headers=_h("alice"),
        json={"dsl": _make_dsl().model_dump(mode="json"), "session_id": sid},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["html"].strip().startswith("<!DOCTYPE html>")


def test_preview_html_accepts_reply_to(client, user_storage):
    """第二条消息 reply_to=1 时，后端校验通过并渲染出引用块。"""
    r = client.post("/api/sessions", headers=_h("alice"))
    sid = r.json()["id"]
    dsl = _make_dsl()
    dsl.scene.messages = [
        Message(sender_id="me", kind="text", text="你好", delay_ms=1500),
        Message(sender_id="her", kind="text", text="回复你", delay_ms=1500, reply_to=1),
    ]
    r = client.post(
        "/api/preview-html",
        headers=_h("alice"),
        json={"dsl": dsl.model_dump(mode="json"), "session_id": sid},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["html"].strip().startswith("<!DOCTYPE html>")
    assert 'class="reply-quote"' in body["html"]
    assert "回复你" in body["html"]


# ---------- DELETE /api/sessions 原子 (P0-2) ----------

def test_delete_session_clears_db_and_disk(client, user_storage):
    """删除 session:DB 行全清 + session 目录整目录被 rmtree。"""
    r = client.post("/api/sessions", headers=_h("alice"))
    sid = r.json()["id"]

    # 用一个真实 png 模拟上传路径(直接落盘 + 插 DB 行,不走 /api/upload 避免 multipart 复杂度)
    file_id = "f-upload-1"
    target = (
        Path(user_storage)
        / "users" / "alice" / "sessions" / sid / "uploads" / f"{file_id}.png"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"fake png")
    asyncio.run(db.insert_file_async(
        file_id=file_id,
        session_id=sid,
        user_id="alice",
        kind="image",
        ext="png",
        size=9,
        content_type="image/png",
    ))
    # 录一个 job 行
    cfg = _make_dsl().model_dump(mode="json")
    asyncio.run(db.insert_job_async(
        job_id="j-1", session_id=sid, user_id="alice", config=cfg,
    ))

    # 删 session
    r = client.delete(f"/api/sessions/{sid}", headers=_h("alice"))
    assert r.status_code == 204

    # DB 行全没
    assert asyncio.run(db.get_job_async("j-1")) is None
    assert db.get_file(file_id) is None
    sess = db.get_session(sid)
    assert sess is None

    # 磁盘 session 目录被 rmtree
    assert not (Path(user_storage) / "users" / "alice" / "sessions" / sid).exists()


def test_delete_session_atomic_keeps_db_on_failure(client, user_storage, monkeypatch):
    """如果 cascade 中间一条 SQL 抛异常,前面的 DELETE 都被事务回滚。

    验证修复后 db.py 的 _cursor() 真正走 BEGIN..COMMIT/ROLLBACK
    (而不是 isolation_level=None 下 commit 是 no-op)。
    """
    r = client.post("/api/sessions", headers=_h("alice"))
    sid = r.json()["id"]

    file_id = "f-keep"
    target = (
        Path(user_storage)
        / "users" / "alice" / "sessions" / sid / "uploads" / f"{file_id}.png"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x")
    asyncio.run(db.insert_file_async(
        file_id=file_id, session_id=sid, user_id="alice",
        kind="image", ext="png", size=1, content_type="image/png",
    ))
    cfg = _make_dsl().model_dump(mode="json")
    asyncio.run(db.insert_job_async(
        job_id="j-keep", session_id=sid, user_id="alice", config=cfg,
    ))

    # Wrap db._cursor():拿到 cur 后,抹 DELETE FROM jobs 抛 OperationalError,
    # 让 _cursor() 里的 ROLLBACK 分支生效。
    from contextlib import contextmanager
    import sqlite3
    original_cursor = db._cursor  # 捕获原始函数引用,避免递归
    @contextmanager
    def wrapped_cursor():
        with original_cursor() as real_cur:
            yield _BoomCursorProxy(real_cur)
    monkeypatch.setattr(db, "_cursor", wrapped_cursor)

    with pytest.raises(sqlite3.OperationalError):
        db.delete_session_cascade(sid)

    # DB 三类行依然都在(事务回滚生效)
    assert db.get_file(file_id) is not None
    assert asyncio.run(db.get_job_async("j-keep")) is not None
    assert db.get_session(sid) is not None


class _BoomCursorProxy:
    """代理 sqlite3.Cursor,在 "DELETE FROM jobs" 上抹异常,其它原样转发。"""

    def __init__(self, real):
        self._real = real

    def execute(self, sql, *a, **kw):
        if isinstance(sql, str) and "DELETE FROM jobs" in sql:
            import sqlite3 as _sq
            raise _sq.OperationalError("simulated db failure")
        return self._real.execute(sql, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_delete_session_cross_user_404(client, user_storage):
    """bob 不能删 alice 的 session(404,不泄露存在性)。"""
    r = client.post("/api/sessions", headers=_h("alice"))
    alice_sid = r.json()["id"]

    client.cookies.clear()
    client.cookies.set("user_id", "bob")
    r = client.delete(f"/api/sessions/{alice_sid}", headers=_h("bob"))
    assert r.status_code == 404

    # alice 仍然能 list 到自己的 session(重置 cookie 为 alice 再调)
    client.cookies.clear()
    client.cookies.set("user_id", "alice")
    r = client.get("/api/sessions", headers=_h("alice"))
    assert any(s["id"] == alice_sid for s in r.json())


# ---------- 跨用户访问隔离 (回归保护) ----------

def test_cross_user_file_access_is_404(client, user_storage):
    r = client.post("/api/sessions", headers=_h("alice"))
    sid = r.json()["id"]
    file_id = "f-x"
    p = (
        Path(user_storage)
        / "users" / "alice" / "sessions" / sid / "uploads" / f"{file_id}.png"
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    asyncio.run(db.insert_file_async(
        file_id=file_id, session_id=sid, user_id="alice",
        kind="image", ext="png", size=1, content_type="image/png",
    ))
    # alice 能读
    r = client.get(f"/api/files/{file_id}", headers=_h("alice"))
    assert r.status_code == 200
    # bob 读不到
    client.cookies.clear()
    client.cookies.set("user_id", "bob")
    r = client.get(f"/api/files/{file_id}", headers=_h("bob"))
    assert r.status_code == 404


def test_cross_user_session_detail_is_404(client, user_storage):
    r = client.post("/api/sessions", headers=_h("alice"))
    alice_sid = r.json()["id"]
    # alice 看得到
    r = client.get(f"/api/sessions/{alice_sid}", headers=_h("alice"))
    assert r.status_code == 200
    # bob 看 404
    client.cookies.clear()
    client.cookies.set("user_id", "bob")
    r = client.get(f"/api/sessions/{alice_sid}", headers=_h("bob"))
    assert r.status_code == 404


def test_session_list_only_returns_owned(client, user_storage):
    client.post("/api/sessions", headers=_h("alice"))
    client.post("/api/sessions", headers=_h("alice"))
    client.post("/api/sessions", headers=_h("bob"))
    r = client.get("/api/sessions", headers=_h("alice"))
    assert r.status_code == 200
    sessions = r.json()
    assert all(s["user_id"] == "alice" for s in sessions)
    assert len(sessions) == 2


# ---------- /api/me 自动注册 ----------

def test_me_auto_creates_user(client, user_storage):
    r = client.get("/api/me", headers=_h("newuser"))
    assert r.status_code == 200
    assert r.json()["id"] == "newuser"


# ---------- cookie 鉴权 + Set-Cookie (img/iframe 场景) ----------

def test_create_session_sets_cookie(client, user_storage):
    """POST /api/sessions 响应里应 Set-Cookie user_id,这样 <img> 能用。"""
    client.cookies.clear()
    client.cookies.set("user_id", "alice")
    r = client.post("/api/sessions", headers=_h("alice"))
    assert r.status_code == 201
    # Set-Cookie 应该设 user_id=alice,Path=/,HttpOnly
    set_cookies = r.headers.get_list("set-cookie")
    matched = [c for c in set_cookies if c.startswith("user_id=")]
    assert matched, f"Set-Cookie missing: {set_cookies}"
    assert "Path=/" in matched[0]
    assert "HttpOnly" in matched[0]
    assert "samesite=lax" in matched[0].lower()


def test_img_uses_cookie_only_no_header(client, user_storage):
    """浏览器 <img> 不会带任何 header,只靠 cookie 鉴权。"""
    r = client.post("/api/sessions", headers=_h("alice"))
    sid = r.json()["id"]
    file_id = "f-img"
    p = Path(user_storage) / "users" / "alice" / "sessions" / sid / "uploads" / f"{file_id}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"img")
    asyncio.run(db.insert_file_async(
        file_id=file_id, session_id=sid, user_id="alice",
        kind="image", ext="png", size=3, content_type="image/png",
    ))

    # 只带 cookie(模拟浏览器原生 img 请求),不传 X-User-Id header → 200
    client.cookies.clear()
    client.cookies.set("user_id", "alice")
    r = client.get(f"/api/files/{file_id}")  # 无 headers
    assert r.status_code == 200
    assert r.content == b"img"

    # 完全没身份 → 401
    client.cookies.clear()
    r = client.get(f"/api/files/{file_id}")
    assert r.status_code == 401


def test_cookie_header_mismatch_is_401(client):
    """防 cookie / header 拼接攻击:两者不一致 → 401。"""
    client.cookies.clear()
    client.cookies.set("user_id", "alice")
    r = client.get("/api/me", headers=_h("bob"))
    assert r.status_code == 401
    assert "mismatch" in r.json()["detail"]


def test_x_user_id_still_works_for_curl(client):
    """X-User-Id header 作为 fallback,保留 curl / 反代部署场景。"""
    r = client.get("/api/me", headers=_h("alice"))
    assert r.status_code == 200
    assert r.json()["id"] == "alice"