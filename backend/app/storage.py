"""文件存储管理 — 见 docs/05-deployment.md §5.12、docs/03-api.md §3.7。

新版布局(2024-Q4 引入多用户隔离):

    storage/
      wechat-video-gen.db                       # SQLite
      users/
        {user_id}/
          sessions/
            {session_id}/
              uploads/{file_id}.{ext}            # 本 session 的素材(头像/图片/背景)
              outputs/{job_id}.{ext}             # 本 session 的产物(MP4)

每个文件/产物都隶属于一个 (user_id, session_id),跨用户物理隔离。
前端拿到的 URL 是 `/api/files/{file_id}` / `/api/jobs/{id}/output`,
后端用 file_id / job_id 查 DB 拿到所属 user 后再返回内容,不再走静态挂载。

旧的 `storage/uploads/` 与 `storage/outputs/` 顶层目录不再创建。
启动时如果发现遗留文件,只打日志,不动它们(避免误删历史数据)。
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger("storage")

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", Path(__file__).parent.parent / "storage"))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", "2097152"))  # 2MB

# 上传资源在 HTML 中被引用为相对路径 /uploads/xxx;
# 录制/预览时需要绝对 URL 才能被浏览器加载。
# 本地开发默认 http://localhost:8000,部署时通过环境变量覆盖。
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

# MIME → 扩展名
ALLOWED_MIME: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}

OUTPUT_EXT = "mp4"


# ---------- 路径辅助 ----------

def user_dir(user_id: str) -> Path:
    return STORAGE_DIR / "users" / user_id


def session_dir(user_id: str, session_id: str) -> Path:
    return user_dir(user_id) / "sessions" / session_id


def upload_dir(user_id: str, session_id: str) -> Path:
    d = session_dir(user_id, session_id) / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def output_dir(user_id: str, session_id: str) -> Path:
    d = session_dir(user_id, session_id) / "outputs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def upload_path(user_id: str, session_id: str, file_id: str, ext: str) -> Path:
    return upload_dir(user_id, session_id) / f"{file_id}.{ext}"


def output_path(user_id: str, session_id: str, job_id: str, ext: str = OUTPUT_EXT) -> Path:
    return output_dir(user_id, session_id) / f"{job_id}.{ext}"


def remove_session(user_id: str, session_id: str) -> None:
    """删整个 session 的目录(素材 + 产物),容错。"""
    sd = session_dir(user_id, session_id)
    if sd.exists():
        shutil.rmtree(sd, ignore_errors=True)


def remove_file(user_id: str, session_id: str, file_id: str, ext: str) -> None:
    p = upload_path(user_id, session_id, file_id, ext)
    try:
        p.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("remove_file failed: %s (%s)", p, exc)


def remove_output(user_id: str, session_id: str, job_id: str, ext: str = OUTPUT_EXT) -> None:
    p = output_path(user_id, session_id, job_id, ext)
    try:
        p.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("remove_output failed: %s (%s)", p, exc)


def list_outputs(user_id: str, session_id: str) -> list[Path]:
    d = output_dir(user_id, session_id)
    return sorted(d.glob(f"*.{OUTPUT_EXT}"))


# ---------- 启动期迁移提示 ----------

_LEGACY_TOP_DIRS = (STORAGE_DIR / "uploads", STORAGE_DIR / "outputs")


def warn_legacy_storage() -> None:
    """旧版本用过 storage/uploads 与 storage/outputs 顶层平铺;发现残留就提示一下。"""
    for p in _LEGACY_TOP_DIRS:
        if p.exists() and any(p.iterdir()):
            logger.warning(
                "Legacy flat storage detected at %s — multi-user layout uses "
                "storage/users/{user_id}/sessions/{session_id}/. Move/delete manually "
                "if you don't need the old files.",
                p,
            )