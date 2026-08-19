"""当前用户解析 — 见 docs/05-deployment.md §5.12、§5.13。

鉴权来源(按优先级):
1. `user_id` cookie — 浏览器对 <img> / <iframe> / fetch 同源请求自动带,前端无需任何额外代码
2. `X-User-Id` header — 反向代理 / curl / 测试用,显式声明

两路都给同样的 CurrentUser;任一缺失 → 401。

## AUTH_REQUIRED 配置

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `AUTH_REQUIRED` | `true` | 是否强制鉴权。生产必须保持 `true`;本地开发 / demo 设 `false` 跳过鉴权 |
| `ANONYMOUS_USER_ID` | `anonymous` | AUTH_REQUIRED=false 时使用的占位 user_id(所有请求归此用户) |

AUTH_REQUIRED=false 时:
- 不校验 cookie / header(允许匿名访问)
- 所有文件 / session / job 归 `ANONYMOUS_USER_ID` 用户(单一"伪用户")
- 启动日志会打 WARNING 提醒不要在生产用

未来要替换成 OIDC session cookie 时,只改 get_current_user 一个函数,
业务代码全部走 Depends(get_current_user),不受影响。
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from fastapi import Cookie, Header, HTTPException, status

from app import db

logger = logging.getLogger("auth")

# 限死字符集,避免路径穿越之类的问题。
_USER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


# ---------- 配置 ----------

def _truthy(val: str | None) -> bool:
    """'true' / '1' / 'yes' / 'on' 都视为 true,其它(false / 0 / 空 / 乱七八糟)都是 false。"""
    return val is not None and val.strip().lower() in ("1", "true", "yes", "on")


# 默认 true = 生产安全默认;本地 dev 必须显式 AUTH_REQUIRED=false 才能跳过鉴权。
AUTH_REQUIRED: bool = _truthy(os.getenv("AUTH_REQUIRED", "true"))

# dev 模式下的占位 user_id(所有匿名请求的归属用户)
ANONYMOUS_USER_ID: str = os.getenv("ANONYMOUS_USER_ID", "anonymous")
ANONYMOUS_USER_NAME: str = os.getenv("ANONYMOUS_USER_NAME", "anonymous")

if not AUTH_REQUIRED:
    logger.warning(
        "AUTH_REQUIRED=false: running in LOCAL DEV mode with user '%s'. "
        "All requests are anonymous — NO user isolation. Do NOT use in production.",
        ANONYMOUS_USER_ID,
    )


# ---------- CurrentUser ----------

@dataclass(frozen=True)
class CurrentUser:
    id: str
    username: str

    @property
    def user_id(self) -> str:
        """兼容老代码用的属性名。"""
        return self.id


def _validate_user_id(value: str) -> str:
    if not _USER_ID_RE.match(value):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid user identifier (must match [a-zA-Z0-9_-]{1,64})",
        )
    return value


async def _resolve_user(uid: str) -> CurrentUser:
    """校验格式 + upsert user + 返回 CurrentUser。"""
    user_id = _validate_user_id(uid)
    row = await db.upsert_user_async(user_id)
    return CurrentUser(id=row["id"], username=row["username"])


# ---------- 入口 ----------

async def get_current_user(
    user_id_cookie: str | None = Cookie(default=None, alias="user_id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> CurrentUser:
    """FastAPI Depends 入口。

    用法:
        @router.post("/...")
        def handler(user: CurrentUser = Depends(get_current_user)):
            ...

    鉴权流程:
    1. AUTH_REQUIRED=false → 跳过校验,使用 ANONYMOUS_USER_ID(本地 dev)
    2. 两个身份来源都给 → 必须一致,否则 401(防 cookie / header 拼接攻击)
    3. 只给一个 → 用那个
    4. 都没给 → 401
    """
    if not AUTH_REQUIRED:
        return await _resolve_user(ANONYMOUS_USER_ID)

    if user_id_cookie and x_user_id and user_id_cookie != x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user_id cookie and X-User-Id header mismatch",
        )
    uid = user_id_cookie or x_user_id
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing user_id cookie or X-User-Id header",
        )
    return await _resolve_user(uid)


# Cookie 名常量,供 main.py 在 POST /api/sessions 响应里 Set-Cookie 用
SESSION_COOKIE_NAME = "user_id"
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 天