"""压缩包导入 — 见 docs/08-import-package.md。

安全解压 zip → 解析 dsl.json → 改写 URL → 落盘到当前 session。
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from app import db
from app.dsl import VideoDSL
from app.storage import ALLOWED_MIME, MAX_UPLOAD_SIZE, save_upload_bytes, upload_path

logger = logging.getLogger("importer")

# ---------- 配置 ----------

IMPORT_MAX_ZIP_SIZE = int(os.getenv("IMPORT_MAX_ZIP_SIZE", str(200 * 1024 * 1024)))         # 200MB
IMPORT_MAX_UNPACKED_SIZE = int(os.getenv("IMPORT_MAX_UNPACKED_SIZE", str(500 * 1024 * 1024))) # 500MB(给图片解压预留 buffer)
IMPORT_MAX_ENTRIES = int(os.getenv("IMPORT_MAX_ENTRIES", "1000"))
IMPORT_MAX_DEPTH = int(os.getenv("IMPORT_MAX_DEPTH", "8"))
# 单文件压缩比阈值: 解压后/压缩前 > 100 视为 zip bomb
IMPORT_MAX_COMPRESSION_RATIO = int(os.getenv("IMPORT_MAX_COMPRESSION_RATIO", "100"))


# ---------- 异常 ----------

class PackageError(Exception):
    """导入失败的领域异常,带 code + detail。"""

    def __init__(self, code: str, *, reason: str | None = None, http_status: int = 400, **detail: Any):
        super().__init__(reason or code)
        self.code = code
        self.http_status = http_status
        self.detail = {"reason": reason or code, **detail}
        if reason is None:
            self.detail.pop("reason", None)


# ---------- 数据结构 ----------

@dataclass
class ImportedFile:
    path_in_zip: str
    file_id: str
    url: str
    kind: Literal["avatar", "image", "background"]
    size: int
    deduped: bool


@dataclass
class ImportResult:
    dsl: VideoDSL
    uploaded_files: list[ImportedFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------- MIME 嗅探 ----------

_MIME_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # RIFF....WEBP
)


def detect_mime(data: bytes) -> str:
    """用前若干字节嗅探实际 MIME,不在 ALLOWED_MIME 时返回空字符串。"""
    for magic, mime in _MIME_MAGIC:
        if data.startswith(magic):
            if mime == "image/webp":
                # webp 魔数在 RIFF 头后 8 字节处
                if len(data) >= 12 and data[8:12] == b"WEBP":
                    return mime
                continue
            return mime
    return ""


# ---------- 路径 / URL 工具 ----------

def is_zip_relative_path(url: str) -> bool:
    """判断 URL 是否应被视为 zip 内相对路径。"""
    lower = url.lower()
    if lower.startswith(("http://", "https://", "data:")):
        return False
    if url.startswith("/"):
        return False
    return True


def _normalize_path(p: str) -> str:
    """统一用正斜杠,去掉前后斜杠。"""
    return p.replace("\\", "/").strip("/")


def _has_path_traversal(p: str) -> bool:
    parts = [part for part in _normalize_path(p).split("/") if part]
    return ".." in parts


def _depth(p: str) -> int:
    parts = [part for part in _normalize_path(p).split("/") if part]
    return len(parts)


# ---------- zip 校验 / 解压 ----------

def _check_entry(member: zipfile.ZipInfo, safe_root: Path) -> Path:
    """校验单个 zip 条目,返回安全的目标路径。"""
    name = member.filename

    if _has_path_traversal(name):
        raise PackageError("illegal_package", reason=f"illegal path in zip: {name}")

    # 绝对路径(Windows / Unix)
    if Path(name).is_absolute() or re.match(r"^[a-zA-Z]:", name):
        raise PackageError("illegal_package", reason=f"absolute path in zip: {name}")

    # 符号链接(外部属性低位判断 symlink;不同 OS 标记不同,这里保守处理)
    external = member.external_attr >> 16
    if external & 0o120000 == 0o120000:  # S_IFLNK
        raise PackageError("illegal_package", reason=f"symlink not allowed: {name}")

    target = (safe_root / name).resolve()
    safe_str = str(safe_root).rstrip(os.sep) + os.sep
    if target != safe_root and not str(target).startswith(safe_str):
        raise PackageError("illegal_package", reason=f"illegal path in zip: {name}")

    return target


def _extract_safely(
    zf: zipfile.ZipFile,
    safe_root: Path,
    *,
    max_unpacked_size: int,
    max_entries: int,
    max_single_file_size: int,
    max_depth: int = IMPORT_MAX_DEPTH,
    max_compression_ratio: int = IMPORT_MAX_COMPRESSION_RATIO,
) -> list[tuple[zipfile.ZipInfo, Path]]:
    """安全解压并返回(条目,目标路径)列表,顺便校验大小与数量。"""
    infos = zf.infolist()
    if len(infos) > max_entries:
        raise PackageError(
            "too_many_entries",
            http_status=413,
            limit=max_entries,
        )

    # 累加解压前大小
    unpacked_total = sum(m.file_size for m in infos)
    if unpacked_total > max_unpacked_size:
        raise PackageError(
            "unpacked_too_large",
            http_status=413,
            limit=max_unpacked_size,
        )

    extracted: list[tuple[zipfile.ZipInfo, Path]] = []
    written_total = 0

    for member in infos:
        target = _check_entry(member, safe_root)

        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        # 单文件大小(解压前)
        if member.file_size > max_single_file_size:
            raise PackageError(
                "file_too_large",
                http_status=413,
                path=member.filename,
                limit=max_single_file_size,
            )

        # 目录深度
        if _depth(member.filename) > max_depth:
            raise PackageError(
                "illegal_package",
                reason=f"entry too deep: {member.filename}",
            )

        # 压缩比炸弹检查
        if member.compress_size and member.file_size:
            ratio = member.file_size / member.compress_size
            if ratio > max_compression_ratio:
                raise PackageError(
                    "illegal_package",
                    reason=f"suspicious compression ratio for {member.filename}",
                )

        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, target.open("wb") as dst:
            while True:
                chunk = src.read(64 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                written_total += len(chunk)
                if written_total > max_unpacked_size:
                    raise PackageError(
                        "unpacked_too_large",
                        http_status=413,
                        limit=max_unpacked_size,
                    )
                if member.file_size > max_single_file_size:
                    # 边写边检查,虽然前面已用 file_size 判断,但保险
                    raise PackageError(
                        "file_too_large",
                        http_status=413,
                        path=member.filename,
                        limit=max_single_file_size,
                    )

        extracted.append((member, target))

    return extracted


# ---------- manifest ----------

def _load_manifest(temp_root: Path) -> dict[str, str] | None:
    manifest_path = temp_root / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PackageError("bad_manifest", reason=f"manifest.json is not valid JSON: {exc}")
    except Exception as exc:  # pragma: no cover
        raise PackageError("bad_manifest", reason=f"failed to read manifest.json: {exc}")

    files = data.get("files")
    if not isinstance(files, dict):
        raise PackageError("bad_manifest", reason="manifest.json must contain a 'files' object")

    validated: dict[str, str] = {}
    for key, value in files.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise PackageError("bad_manifest", reason="manifest files must be string → string")
        normalized = _normalize_path(value)
        if _has_path_traversal(normalized):
            raise PackageError("bad_manifest", path=value, reason="manifest path contains '..'")
        if Path(normalized).is_absolute():
            raise PackageError("bad_manifest", path=value, reason="manifest path is absolute")
        validated[key] = normalized

    return validated


# ---------- DSL 解析 ----------

def _load_dsl(temp_root: Path) -> dict[str, Any]:
    dsl_path = temp_root / "dsl.json"
    if not dsl_path.is_file():
        raise PackageError(
            "illegal_package",
            reason="missing dsl.json (case-sensitive, must be at zip root)",
        )
    try:
        return json.loads(dsl_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PackageError("illegal_package", reason=f"dsl.json is not valid JSON: {exc}")


def _validate_dsl(raw: dict[str, Any]) -> VideoDSL:
    schema_version = raw.get("schema_version")
    if schema_version != "1.0":
        raise PackageError(
            "schema_version_mismatch",
            expected="1.0",
            got=schema_version,
        )
    try:
        return VideoDSL.model_validate(raw)
    except ValidationError as exc:
        errors = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", []))
            errors.append({"loc": loc, "msg": err.get("msg", ""), "type": err.get("type", "")})
        raise PackageError("dsl_validation_failed", http_status=422, errors=errors) from exc


# ---------- URL 改写 ----------

def _resolve_url_to_path(
    url: str,
    manifest: dict[str, str] | None,
    zip_files: set[str],
) -> tuple[str | None, bool]:
    """把 DSL 里的 URL 解析成 zip 内路径。

    返回 (path_in_zip, used_manifest)。如果 URL 不应被改写,返回 (None, False)。
    """
    if not is_zip_relative_path(url):
        return None, False

    key = url.strip()
    if manifest and key in manifest:
        return manifest[key], True

    normalized = _normalize_path(key)
    if normalized in zip_files:
        return normalized, False

    return None, False


def _collect_referenced_paths(
    dsl: VideoDSL,
    manifest: dict[str, str] | None,
    zip_files: set[str],
) -> tuple[dict[str, ImportedFile], list[str]]:
    """遍历 DSL,收集需要导入的图片路径与用途,同时发现缺失文件。"""
    referenced: dict[str, ImportedFile] = {}
    missing: list[str] = []

    def add_ref(path: str, kind: Literal["avatar", "image", "background"]) -> None:
        if path not in referenced:
            referenced[path] = ImportedFile(
                path_in_zip=path,
                file_id="",
                url="",
                kind=kind,
                size=0,
                deduped=False,
            )
        else:
            # 用途优先级: background > avatar > image
            order = {"background": 0, "avatar": 1, "image": 2}
            if order[kind] < order[referenced[path].kind]:
                referenced[path].kind = kind

    scene = dsl.scene

    # background
    if scene.background_image_url:
        p, _ = _resolve_url_to_path(scene.background_image_url, manifest, zip_files)
        if p is not None:
            add_ref(p, "background")
        elif is_zip_relative_path(scene.background_image_url):
            missing.append(scene.background_image_url)

    # participants
    for participant in scene.participants:
        if participant.avatar_url:
            p, _ = _resolve_url_to_path(participant.avatar_url, manifest, zip_files)
            if p is not None:
                add_ref(p, "avatar")
            elif is_zip_relative_path(participant.avatar_url):
                missing.append(participant.avatar_url)

    # messages
    for idx, message in enumerate(scene.messages):
        if message.image_url:
            p, _ = _resolve_url_to_path(message.image_url, manifest, zip_files)
            if p is not None:
                add_ref(p, "image")
            elif is_zip_relative_path(message.image_url):
                missing.append(message.image_url)

        if message.cover_url:
            p, _ = _resolve_url_to_path(message.cover_url, manifest, zip_files)
            if p is not None:
                add_ref(p, "image")
            elif is_zip_relative_path(message.cover_url):
                missing.append(message.cover_url)

        # video_url 特殊处理
        if message.video_url:
            vurl = message.video_url.strip()
            resolved: str | None = None
            used_manifest = False
            if manifest and vurl in manifest:
                resolved = manifest[vurl]
                used_manifest = True
            elif is_zip_relative_path(vurl):
                normalized = _normalize_path(vurl)
                if normalized in zip_files:
                    resolved = normalized

            if resolved is not None:
                raise PackageError(
                    "unsupported_video_url",
                    reason=(
                        f"Message[{idx}].video_url points to a file inside the zip; "
                        "video body is not importable in this release"
                    ),
                    message_index=idx,
                    offending_path=resolved,
                    used_manifest=used_manifest,
                )
            elif is_zip_relative_path(vurl):
                missing.append(vurl)

    return referenced, missing


def _rewrite_dsl(
    dsl: VideoDSL,
    manifest: dict[str, str] | None,
    zip_files: set[str],
    uploads: dict[str, ImportedFile],
) -> VideoDSL:
    """根据已导入文件,把 DSL 中所有 zip 内图片 URL 改写成 /api/files/{file_id}。"""

    def rewrite(url: str | None) -> str | None:
        if not url:
            return url
        p, _ = _resolve_url_to_path(url, manifest, zip_files)
        if p is not None and p in uploads:
            return uploads[p].url
        return url

    scene = dsl.scene
    scene.background_image_url = rewrite(scene.background_image_url)
    for participant in scene.participants:
        participant.avatar_url = rewrite(participant.avatar_url)
    for message in scene.messages:
        message.image_url = rewrite(message.image_url)
        message.cover_url = rewrite(message.cover_url)
        # video_url 不动(前面已拦截 zip 内路径)
    return dsl


# ---------- 文件导入 / 去重 ----------

def _build_md5_index(session_id: str) -> dict[str, str]:
    """构建当前 session 已有文件的 md5 → file_id 索引。"""
    index: dict[str, str] = {}
    for row in db.list_session_files(session_id):
        md5 = row.get("md5")
        if md5:
            index[md5] = row["id"]
            continue
        # 兼容旧数据:从磁盘读取计算 md5
        user_id = row["user_id"]
        ext = row["ext"]
        path = upload_path(user_id, session_id, row["id"], ext)
        try:
            data = path.read_bytes()
        except OSError:
            continue
        index[hashlib.md5(data).hexdigest()] = row["id"]
    return index


def _import_files(
    temp_root: Path,
    referenced: dict[str, ImportedFile],
    session_id: str,
    user_id: str,
) -> dict[str, ImportedFile]:
    md5_index = _build_md5_index(session_id)
    uploads: dict[str, ImportedFile] = {}

    for path_in_zip, meta in referenced.items():
        source = temp_root / path_in_zip
        if not source.is_file():
            # 理论上前面已经校验过存在性,防御性报错
            raise PackageError(
                "missing_files_in_zip",
                missing=[path_in_zip],
            )

        data = source.read_bytes()
        if not data:
            raise PackageError(
                "illegal_package",
                reason=f"empty file in zip: {path_in_zip}",
            )
        if len(data) > MAX_UPLOAD_SIZE:
            raise PackageError(
                "file_too_large",
                http_status=413,
                path=path_in_zip,
                limit=MAX_UPLOAD_SIZE,
            )

        detected = detect_mime(data)
        if detected not in ALLOWED_MIME:
            raise PackageError(
                "bad_mime",
                path=path_in_zip,
                detected_mime=detected or "unknown",
            )

        ext = ALLOWED_MIME[detected]
        md5 = hashlib.md5(data).hexdigest()

        if md5 in md5_index:
            file_id = md5_index[md5]
            uploads[path_in_zip] = ImportedFile(
                path_in_zip=path_in_zip,
                file_id=file_id,
                url=f"/api/files/{file_id}",
                kind=meta.kind,
                size=len(data),
                deduped=True,
            )
            continue

        file_id, _, _, content_type = save_upload_bytes(
            user_id=user_id,
            session_id=session_id,
            data=data,
            ext=ext,
            kind=meta.kind,
        )
        db.insert_file(
            file_id=file_id,
            session_id=session_id,
            user_id=user_id,
            kind=meta.kind,
            ext=ext,
            size=len(data),
            content_type=content_type,
            md5=md5,
        )
        md5_index[md5] = file_id
        uploads[path_in_zip] = ImportedFile(
            path_in_zip=path_in_zip,
            file_id=file_id,
            url=f"/api/files/{file_id}",
            kind=meta.kind,
            size=len(data),
            deduped=False,
        )

    return uploads


# ---------- 主入口 ----------

def import_package(
    zip_bytes: bytes,
    session_id: str,
    user_id: str,
    *,
    max_zip_size: int = IMPORT_MAX_ZIP_SIZE,
    max_unpacked_size: int = IMPORT_MAX_UNPACKED_SIZE,
    max_entries: int = IMPORT_MAX_ENTRIES,
    max_single_file_size: int = MAX_UPLOAD_SIZE,
) -> ImportResult:
    """解压 → 校验 → 改写 → 落盘;失败抛 PackageError。"""
    if len(zip_bytes) > max_zip_size:
        raise PackageError(
            "package_too_large",
            http_status=413,
            limit=max_zip_size,
        )

    temp_root_path: Path | None = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            temp_root_path = Path(tmp)
            safe_root = temp_root_path.resolve()

            # 校验是合法 zip
            try:
                with io.BytesIO(zip_bytes) as bio, zipfile.ZipFile(bio) as zf:
                    _extract_safely(
                        zf,
                        safe_root,
                        max_unpacked_size=max_unpacked_size,
                        max_entries=max_entries,
                        max_single_file_size=max_single_file_size,
                    )
            except zipfile.BadZipFile as exc:
                raise PackageError("illegal_package", reason=f"not a valid zip file: {exc}") from exc

            # 校验 dsl.json
            raw_dsl = _load_dsl(safe_root)
            dsl = _validate_dsl(raw_dsl)

            # manifest
            manifest = _load_manifest(safe_root)

            # zip 内所有文件路径集合
            zip_files = {
                _normalize_path(str(p.relative_to(safe_root)))
                for p in safe_root.rglob("*")
                if p.is_file()
            }

            # 校验 manifest 引用的文件存在
            if manifest:
                bad = [v for v in manifest.values() if v not in zip_files]
                if bad:
                    raise PackageError(
                        "bad_manifest",
                        reason="manifest references files not present in zip",
                        missing=bad,
                    )

            # 收集引用 + 缺失检查
            referenced, missing = _collect_referenced_paths(dsl, manifest, zip_files)
            if missing:
                raise PackageError(
                    "missing_files_in_zip",
                    missing=sorted(set(missing)),
                )

            # 导入文件
            uploads = _import_files(safe_root, referenced, session_id, user_id)

            # 改写 DSL
            dsl = _rewrite_dsl(dsl, manifest, zip_files, uploads)

            # 生成 warnings: zip 内非 dsl.json/manifest.json 且未被引用的文件
            ignored = sorted(
                p for p in zip_files
                if p not in ("dsl.json", "manifest.json") and p not in uploads
            )
            warnings = [f"{p} 在 zip 内但未被任何 DSL URL 引用(已忽略)" for p in ignored]

            return ImportResult(
                dsl=dsl,
                uploaded_files=list(uploads.values()),
                warnings=warnings,
            )
    except PackageError:
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("unexpected import error")
        raise PackageError("illegal_package", reason=f"unexpected error: {exc}") from exc
    finally:
        # TemporaryDirectory 上下文已负责清理;这里再保险一层
        if temp_root_path is not None and temp_root_path.exists():
            shutil.rmtree(temp_root_path, ignore_errors=True)
