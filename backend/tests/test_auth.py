"""鉴权依赖测试 — X-User-Id / cookie 解析 + AUTH_REQUIRED 配置。"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from app import auth, db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_schema()
    yield


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/me")
    def me(user: auth.CurrentUser = Depends(auth.get_current_user)):
        return {"id": user.id, "username": user.username}

    return app


def test_missing_header_returns_401():
    """默认(AUTH_REQUIRED=true)下缺 X-User-Id → 401。"""
    client = TestClient(_build_app())
    r = client.get("/me")
    assert r.status_code == 401
    assert "missing" in r.json()["detail"]


def test_invalid_header_returns_401():
    client = TestClient(_build_app())
    r = client.get("/me", headers={"X-User-Id": "../etc/passwd"})
    assert r.status_code == 401
    assert "invalid" in r.json()["detail"]


def test_valid_header_auto_creates_user():
    client = TestClient(_build_app())
    r = client.get("/me", headers={"X-User-Id": "alice"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "alice"
    row = db.get_user("alice")
    assert row is not None
    assert row["username"] == "alice"


def test_second_call_returns_same_user():
    client = TestClient(_build_app())
    r1 = client.get("/me", headers={"X-User-Id": "bob"})
    r2 = client.get("/me", headers={"X-User-Id": "bob"})
    assert r1.json() == r2.json()


def test_cookie_path():
    """cookie 鉴权路径,与 header 等价。"""
    client = TestClient(_build_app())
    client.cookies.set("user_id", "carol")
    r = client.get("/me")
    assert r.status_code == 200
    assert r.json()["id"] == "carol"


def test_cookie_header_mismatch_returns_401():
    """cookie + header 给不同 user → 401(防拼接攻击)。"""
    client = TestClient(_build_app())
    client.cookies.set("user_id", "alice")
    r = client.get("/me", headers={"X-User-Id": "bob"})
    assert r.status_code == 401
    assert "mismatch" in r.json()["detail"]


# ---------- AUTH_REQUIRED=false 本地开发模式 ----------

@pytest.fixture
def dev_mode(monkeypatch):
    """把 auth 模块切到 dev 模式(AUTH_REQUIRED=false + 自定义匿名 user_id)。"""
    monkeypatch.setattr(auth, "AUTH_REQUIRED", False)
    monkeypatch.setattr(auth, "ANONYMOUS_USER_ID", "local-dev")
    yield


def test_dev_mode_skips_auth_no_cookie_no_header(dev_mode):
    """dev 模式:无 cookie / 无 header 也能访问,user 是 ANONYMOUS_USER_ID。"""
    client = TestClient(_build_app())
    r = client.get("/me")
    assert r.status_code == 200
    assert r.json()["id"] == "local-dev"


def test_dev_mode_ignores_header_value(dev_mode):
    """dev 模式:X-User-Id header 仍然被忽略(所有请求归 anonymous)。"""
    client = TestClient(_build_app())
    r = client.get("/me", headers={"X-User-Id": "alice"})
    assert r.status_code == 200
    assert r.json()["id"] == "local-dev"  # 不是 alice


def test_dev_mode_creates_anonymous_user_row(dev_mode):
    """dev 模式匿名请求也会在 users 表里建一行(便于 session/file 归属)。"""
    client = TestClient(_build_app())
    client.get("/me")
    row = db.get_user("local-dev")
    assert row is not None


def test_dev_mode_warning_at_import(caplog):
    """import 时如果 AUTH_REQUIRED=false,打 WARNING 日志。

    注意:这测的是 module 加载时的日志(不是单测运行时改的 AUTH_REQUIRED)。
    """
    import logging
    # 模拟启动时 env var
    os.environ["AUTH_REQUIRED"] = "false"
    try:
        with caplog.at_level(logging.WARNING, logger="auth"):
            importlib.reload(auth)
            # reload 会重新跑模块顶层代码,_truthy 会重新读 env
            assert auth.AUTH_REQUIRED is False
        assert any("AUTH_REQUIRED=false" in rec.message for rec in caplog.records)
    finally:
        # 恢复
        if "AUTH_REQUIRED" in os.environ:
            del os.environ["AUTH_REQUIRED"]
        importlib.reload(auth)


def test_production_default_is_secure():
    """AUTH_REQUIRED 默认值是 true(安全默认)。"""
    # 不设 env var,模块加载时默认值
    assert auth.AUTH_REQUIRED is True