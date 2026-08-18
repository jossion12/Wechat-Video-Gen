"""文件存储管理 — 见 docs/05-deployment.md §5.12。"""

from __future__ import annotations

import os
from pathlib import Path

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", Path(__file__).parent.parent / "storage"))
UPLOADS = STORAGE_DIR / "uploads"
OUTPUTS = STORAGE_DIR / "outputs"

for _p in (UPLOADS, OUTPUTS):
    _p.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", "2097152"))  # 2MB

# MIME → 扩展名
ALLOWED_MIME: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}
