"""文件存储管理 — 见 docs/05-deployment.md §5.12、docs/03-api.md §3.7。

新版布局(2024-Q4 引入多用户隔离):

    storage/
      dialogue-theater.db                       # SQLite
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
import uuid
from pathlib import Path

logger = logging.getLogger("storage")

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", Path(__file__).parent.parent / "storage"))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", "10485760"))  # 10MB

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

# 扩展名 → MIME(用于从文件扩展名推断 content_type)
EXT_TO_MIME: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    # TTS 多角色对话合成(2025-Q3):ASR JSON 上传走 /api/tts/import-asr,
    # 复用 save_upload_bytes 落盘,这里把 json 加进白名单(它不是图片素材,不会
    # 进 /api/upload,只被 TTS 端点用)。
    "json": "application/json",
}

OUTPUT_EXT = "mp4"
# 透明背景产物的扩展名。video 容器本身决定透明与否(VP9 + yuva420p / ProRes 4444),
# 见 backend/app/recorder.py::render_video_transparent。
OUTPUT_EXT_WEBM_ALPHA = "webm"
OUTPUT_EXT_MOV_PRORES = "mov"
# TTS 多角色对话合成产物的扩展名(wav,24kHz mono)。见 backend/app/tts_service.py。
EXT_AUDIO_WAV = "wav"

# 时间码 JSON 的扩展名(后缀固定,不随产物格式变化 —— 不透明/透明两条产物线都共用
# 同一个 timeline.json)。见 backend/app/recorder.py 与 docs/03-api.md §3.x 时间码段。
TIMELINE_EXT = "timeline.json"
TIMELINE_MIME = "application/json"

# 扩展名 → 产物 MIME(供 serve_output 正确响应客户端)
OUTPUT_MIME: dict[str, str] = {
    OUTPUT_EXT: "video/mp4",
    OUTPUT_EXT_WEBM_ALPHA: "video/webm",
    OUTPUT_EXT_MOV_PRORES: "video/quicktime",
    EXT_AUDIO_WAV: "audio/wav",
}


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


def save_upload_bytes(
    user_id: str,
    session_id: str,
    data: bytes,
    ext: str,
    kind: str,
    file_id: str | None = None,
    content_type: str | None = None,
) -> tuple[str, Path, str, str | None]:
    """把上传字节写入磁盘并返回 (file_id, path, ext, content_type)。

    不操作数据库 —— 调用方负责 insert_file。路径生成与 /api/upload 保持一致。
    """
    if ext not in EXT_TO_MIME:
        raise ValueError(f"unsupported ext: {ext}")
    if content_type is None:
        content_type = EXT_TO_MIME.get(ext)
    fid = file_id or uuid.uuid4().hex[:26]
    target = upload_path(user_id, session_id, fid, ext)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return fid, target, ext, content_type


def output_path(user_id: str, session_id: str, job_id: str, ext: str = OUTPUT_EXT) -> Path:
    return output_dir(user_id, session_id) / f"{job_id}.{ext}"


def timeline_path(user_id: str, session_id: str, job_id: str) -> Path:
    """timeline.json 路径 —— 与 mp4/webm/mov 产物同目录,文件名 `{job_id}.timeline.json`。

    见 docs/03-api.md §3.x 时间码导出。
    """
    return output_dir(user_id, session_id) / f"{job_id}.{TIMELINE_EXT}"


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


def remove_timeline(user_id: str, session_id: str, job_id: str) -> None:
    """删 timeline.json(渲染失败清理时与 mp4/webm/mov 一起清),容错。"""
    p = timeline_path(user_id, session_id, job_id)
    try:
        p.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("remove_timeline failed: %s (%s)", p, exc)


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