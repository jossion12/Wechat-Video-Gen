"""压缩包导入单元测试 + 安全测试 — 见 docs/08-import-package.md §8.11。"""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import pytest

from app import db, importer
from app.storage import upload_path


@pytest.fixture(autouse=True)
def isolated_app(tmp_path, monkeypatch):
    """每例:DB 与 STORAGE_DIR 都指到 tmp_path。"""
    test_db = tmp_path / "test.db"
    test_storage = tmp_path / "storage"
    test_storage.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(db, "DB_PATH", test_db)
    from app import storage as storage_pkg
    monkeypatch.setattr(storage_pkg, "STORAGE_DIR", test_storage)
    db.init_schema()
    yield test_storage


@pytest.fixture
def user_storage(isolated_app):
    return isolated_app


def _make_session(user_id: str = "alice") -> str:
    db.upsert_user(user_id)
    sid = db.create_session(user_id, f"sess-{user_id}-1", title="test")
    return sid["id"]


def _png_bytes() -> bytes:
    """最小可识别 PNG。"""
    return bytes.fromhex(
        "89504e470d0a1a0a"          # PNG signature
        "00000001"                  # IHDR length
        "00000001000000010802000000" # IHDR chunk body (1x1)
        "907753de"                  # IHDR CRC (fake but accepted by sniff)
        "00000000"                  # IEND length
        "49454e44ae426082"          # IEND chunk
    )


def _jpg_bytes() -> bytes:
    """最小可识别 JPEG。"""
    return bytes.fromhex(
        "ffd8ffe000104a4649460001"  # JPEG SOI + JFIF marker
        "010100000100010000"
        "ffd9"                      # EOI
    )


def _html_bytes_named_png() -> bytes:
    return b"<html><body>not an image</body></html>"


def _png_bytes2() -> bytes:
    """与 _png_bytes 内容不同但同样是 PNG。"""
    return _png_bytes() + b"\x00"


def _jpg_bytes2() -> bytes:
    """与 _jpg_bytes 内容不同但同样是 JPEG。"""
    return _jpg_bytes() + b"\x00"


def _build_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _dsl_json(**kwargs) -> bytes:
    return json.dumps(_dsl(**kwargs), ensure_ascii=False).encode()


def _dsl(
    *,
    schema_version: str = "1.0",
    background_image_url: str | None = "backgrounds/bg.jpg",
    avatar_urls: list[str] | None = None,
    messages: list[dict] | None = None,
) -> dict:
    if avatar_urls is None:
        avatar_urls = ["avatars/alice.png", "avatars/bob.jpg"]
    if messages is None:
        messages = [
            {"sender_id": "p0", "kind": "text", "text": "hi", "delay_ms": 1500},
            {
                "sender_id": "p1",
                "kind": "image",
                "image_url": "images/chat-1.jpg",
                "delay_ms": 1500,
            },
        ]
    return {
        "schema_version": schema_version,
        "kind": "chat",
        "template": "cyberpunk",
        "scene": {
            "mode": "group",
            "title": "test",
            "background": "#0a0a12",
            "background_image_url": background_image_url,
            "style_theme": "cyberpunk",
            "intent": "short_video_drama",
            "intent_acknowledged": True,
            "participants": [
                {"id": f"p{i}", "name": f"User{i}", "avatar_url": url, "persona": ""}
                for i, url in enumerate(avatar_urls)
            ],
            "messages": messages,
            "watermark": {
                "text": "本内容由 AI 生成 · 仅供创意表达",
                "badge_style": "neon",
            },
        },
    }


def _assert_url_rewritten(url: str | None) -> None:
    assert url and url.startswith("/api/files/")


def _assert_url_preserved(url: str | None, expected: str) -> None:
    assert url == expected


# ---------- 正常流程 ----------

def test_import_success_rewrites_urls(user_storage):
    sid = _make_session()
    files = {
        "dsl.json": _dsl_json(),
        "avatars/alice.png": _png_bytes(),
        "avatars/bob.jpg": _jpg_bytes(),
        "backgrounds/bg.jpg": _png_bytes2(),
        "images/chat-1.jpg": _jpg_bytes2(),
    }
    zip_bytes = _build_zip(files)
    result = importer.import_package(zip_bytes, sid, "alice")

    assert result.dsl.schema_version == "1.0"
    _assert_url_rewritten(result.dsl.scene.background_image_url)
    for p in result.dsl.scene.participants:
        _assert_url_rewritten(p.avatar_url)
    assert result.dsl.scene.messages[1].image_url.startswith("/api/files/")
    assert len(result.uploaded_files) == 4
    assert all(not f.deduped for f in result.uploaded_files)


def test_missing_dsl_json(user_storage):
    sid = _make_session()
    zip_bytes = _build_zip({"readme.txt": b"hello"})
    with pytest.raises(importer.PackageError) as exc:
        importer.import_package(zip_bytes, sid, "alice")
    assert exc.value.code == "illegal_package"
    assert "dsl.json" in exc.value.detail.get("reason", "")


def test_missing_files_in_zip(user_storage):
    sid = _make_session()
    files = {
        "dsl.json": _dsl_json(),
        "avatars/alice.png": _png_bytes(),
        "avatars/bob.jpg": _png_bytes(),
        # 缺 backgrounds/bg.jpg and images/chat-1.jpg
    }
    with pytest.raises(importer.PackageError) as exc:
        importer.import_package(_build_zip(files), sid, "alice")
    assert exc.value.code == "missing_files_in_zip"
    assert set(exc.value.detail["missing"]) == {"backgrounds/bg.jpg", "images/chat-1.jpg"}


def test_absolute_url_preserved(user_storage):
    sid = _make_session()
    url = "https://cdn.example.com/bg.jpg"
    dsl = _dsl(
        background_image_url=url,
        avatar_urls=["https://cdn.example.com/a.png", "https://cdn.example.com/b.png"],
        messages=[{"sender_id": "p0", "kind": "text", "text": "hi", "delay_ms": 1500}],
    )
    files = {
        "dsl.json": json.dumps(dsl, ensure_ascii=False).encode(),
    }
    result = importer.import_package(_build_zip(files), sid, "alice")
    _assert_url_preserved(result.dsl.scene.background_image_url, url)
    _assert_url_preserved(result.dsl.scene.participants[0].avatar_url, "https://cdn.example.com/a.png")
    assert result.uploaded_files == []


def test_data_uri_preserved(user_storage):
    sid = _make_session()
    url = "data:image/png;base64,iVBORw0KGgo="
    dsl = _dsl(background_image_url=url)
    files = {
        "dsl.json": json.dumps(dsl, ensure_ascii=False).encode(),
        "avatars/alice.png": _png_bytes(),
        "avatars/bob.jpg": _jpg_bytes(),
        "backgrounds/bg.jpg": _jpg_bytes(),
        "images/chat-1.jpg": _jpg_bytes(),
    }
    result = importer.import_package(_build_zip(files), sid, "alice")
    _assert_url_preserved(result.dsl.scene.background_image_url, url)


def test_manifest_priority(user_storage):
    sid = _make_session()
    dsl = _dsl(
        background_image_url="bg_alias",
        avatar_urls=["alice_alias", "bob_alias"],
    )
    messages = list(dsl["scene"]["messages"])
    messages[1]["image_url"] = "chat_alias"
    dsl["scene"]["messages"] = messages
    files = {
        "dsl.json": json.dumps(dsl, ensure_ascii=False).encode(),
        "manifest.json": json.dumps({
            "files": {
                "bg_alias": "backgrounds/bg.jpg",
                "alice_alias": "avatars/alice.png",
                "bob_alias": "avatars/bob.jpg",
                "chat_alias": "images/chat-1.jpg",
            }
        }, ensure_ascii=False).encode(),
        "avatars/alice.png": _png_bytes(),
        "avatars/bob.jpg": _png_bytes(),
        "backgrounds/bg.jpg": _jpg_bytes(),
        "images/chat-1.jpg": _jpg_bytes(),
    }
    result = importer.import_package(_build_zip(files), sid, "alice")
    _assert_url_rewritten(result.dsl.scene.background_image_url)
    _assert_url_rewritten(result.dsl.scene.messages[1].image_url)


def test_video_url_https_preserved(user_storage):
    sid = _make_session()
    dsl = _dsl(messages=[
        {"sender_id": "p0", "kind": "text", "text": "hi", "delay_ms": 1500},
        {
            "sender_id": "p1",
            "kind": "video",
            "video_url": "https://cdn.example.com/clip.mp4",
            "cover_url": "images/cover.jpg",
            "duration": "0:10",
            "delay_ms": 1500,
        },
    ])
    files = {
        "dsl.json": json.dumps(dsl, ensure_ascii=False).encode(),
        "avatars/alice.png": _png_bytes(),
        "avatars/bob.jpg": _png_bytes(),
        "backgrounds/bg.jpg": _jpg_bytes(),
        "images/cover.jpg": _jpg_bytes(),
    }
    result = importer.import_package(_build_zip(files), sid, "alice")
    msg = result.dsl.scene.messages[1]
    _assert_url_preserved(msg.video_url, "https://cdn.example.com/clip.mp4")
    _assert_url_rewritten(msg.cover_url)
    assert any(f.path_in_zip == "images/cover.jpg" for f in result.uploaded_files)


def test_video_url_zip_path_rejected(user_storage):
    sid = _make_session()
    dsl = _dsl(messages=[
        {"sender_id": "p0", "kind": "text", "text": "hi", "delay_ms": 1500},
        {
            "sender_id": "p1",
            "kind": "video",
            "video_url": "videos/clip.mp4",
            "duration": "0:10",
            "delay_ms": 1500,
        },
    ])
    files = {
        "dsl.json": json.dumps(dsl, ensure_ascii=False).encode(),
        "avatars/alice.png": _png_bytes(),
        "avatars/bob.jpg": _png_bytes(),
        "backgrounds/bg.jpg": _jpg_bytes(),
        "videos/clip.mp4": b"fake video",
    }
    with pytest.raises(importer.PackageError) as exc:
        importer.import_package(_build_zip(files), sid, "alice")
    assert exc.value.code == "unsupported_video_url"
    assert exc.value.detail["message_index"] == 1


def test_video_url_manifest_key_rejected(user_storage):
    sid = _make_session()
    dsl = _dsl(messages=[
        {"sender_id": "p0", "kind": "text", "text": "hi", "delay_ms": 1500},
        {
            "sender_id": "p1",
            "kind": "video",
            "video_url": "clip_alias",
            "duration": "0:10",
            "delay_ms": 1500,
        },
    ])
    files = {
        "dsl.json": json.dumps(dsl, ensure_ascii=False).encode(),
        "manifest.json": json.dumps({"files": {"clip_alias": "videos/clip.mp4"}}, ensure_ascii=False).encode(),
        "avatars/alice.png": _png_bytes(),
        "avatars/bob.jpg": _png_bytes(),
        "backgrounds/bg.jpg": _jpg_bytes(),
        "videos/clip.mp4": b"fake video",
    }
    with pytest.raises(importer.PackageError) as exc:
        importer.import_package(_build_zip(files), sid, "alice")
    assert exc.value.code == "unsupported_video_url"


def test_schema_version_mismatch(user_storage):
    sid = _make_session()
    files = {
        "dsl.json": _dsl_json(schema_version="2.0"),
    }
    with pytest.raises(importer.PackageError) as exc:
        importer.import_package(_build_zip(files), sid, "alice")
    assert exc.value.code == "schema_version_mismatch"
    assert exc.value.detail["expected"] == "1.0"


def test_dedup_reuses_file_id(user_storage):
    sid = _make_session()
    files = {
        "dsl.json": _dsl_json(),
        "avatars/alice.png": _png_bytes(),
        "avatars/bob.jpg": _png_bytes(),
        "backgrounds/bg.jpg": _jpg_bytes(),
        "images/chat-1.jpg": _jpg_bytes(),
    }
    result1 = importer.import_package(_build_zip(files), sid, "alice")
    # 同文件再导入一次
    result2 = importer.import_package(_build_zip(files), sid, "alice")

    assert len(result2.uploaded_files) == 4
    assert all(f.deduped for f in result2.uploaded_files)
    ids1 = {f.path_in_zip: f.file_id for f in result1.uploaded_files}
    ids2 = {f.path_in_zip: f.file_id for f in result2.uploaded_files}
    assert ids1 == ids2


def test_unused_files_warning(user_storage):
    sid = _make_session()
    files = {
        "dsl.json": _dsl_json(),
        "avatars/alice.png": _png_bytes(),
        "avatars/bob.jpg": _png_bytes(),
        "backgrounds/bg.jpg": _jpg_bytes(),
        "images/chat-1.jpg": _jpg_bytes(),
        "README.txt": b"hello",
    }
    result = importer.import_package(_build_zip(files), sid, "alice")
    assert any("README.txt" in w for w in result.warnings)


# ---------- 安全测试 ----------

def test_zip_slip_relative(user_storage):
    sid = _make_session()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("dsl.json", _dsl_json())
        zf.writestr("avatars/alice.png", _png_bytes())
        zf.writestr("../../../etc/passwd", b"evil")
    with pytest.raises(importer.PackageError) as exc:
        importer.import_package(buf.getvalue(), sid, "alice")
    assert exc.value.code == "illegal_package"


def test_zip_slip_absolute_windows(user_storage):
    sid = _make_session()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("dsl.json", _dsl_json())
        zf.writestr("C:\\evil.exe", b"evil")
    with pytest.raises(importer.PackageError) as exc:
        importer.import_package(buf.getvalue(), sid, "alice")
    assert exc.value.code == "illegal_package"


def test_symlink_entry_rejected(user_storage):
    sid = _make_session()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("dsl.json", _dsl_json())
        info = zipfile.ZipInfo("evil_link")
        # 设置 Unix symlink 外部属性
        info.external_attr = (0o120777 << 16) | 0o777
        zf.writestr(info, "/etc/passwd")
    with pytest.raises(importer.PackageError) as exc:
        importer.import_package(buf.getvalue(), sid, "alice")
    assert exc.value.code == "illegal_package"


def test_package_too_large(user_storage):
    sid = _make_session()
    zip_bytes = _build_zip({"dsl.json": b"{}"})
    with pytest.raises(importer.PackageError) as exc:
        importer.import_package(zip_bytes, sid, "alice", max_zip_size=1)
    assert exc.value.code == "package_too_large"
    assert exc.value.http_status == 413


def test_unpacked_too_large(user_storage):
    sid = _make_session()
    files = {
        "dsl.json": _dsl_json(),
        "avatars/alice.png": _png_bytes(),
    }
    zip_bytes = _build_zip(files)
    with pytest.raises(importer.PackageError) as exc:
        importer.import_package(zip_bytes, sid, "alice", max_unpacked_size=1)
    assert exc.value.code == "unpacked_too_large"
    assert exc.value.http_status == 413


def test_too_many_entries(user_storage):
    sid = _make_session()
    files = {"dsl.json": _dsl_json()}
    for i in range(5):
        files[f"x{i}.png"] = _png_bytes()
    zip_bytes = _build_zip(files)
    with pytest.raises(importer.PackageError) as exc:
        importer.import_package(zip_bytes, sid, "alice", max_entries=2)
    assert exc.value.code == "too_many_entries"
    assert exc.value.http_status == 413


def test_single_file_too_large(user_storage):
    sid = _make_session()
    files = {
        "dsl.json": _dsl_json(),
        "avatars/alice.png": b"x" * 10,
    }
    zip_bytes = _build_zip(files)
    with pytest.raises(importer.PackageError) as exc:
        importer.import_package(zip_bytes, sid, "alice", max_single_file_size=5)
    assert exc.value.code == "file_too_large"
    assert exc.value.http_status == 413


def test_bad_mime_html_named_png(user_storage):
    sid = _make_session()
    files = {
        "dsl.json": _dsl_json(),
        "avatars/alice.png": _png_bytes(),
        "avatars/bob.jpg": _png_bytes(),
        "backgrounds/bg.jpg": _jpg_bytes(),
        "images/chat-1.jpg": _html_bytes_named_png(),
    }
    with pytest.raises(importer.PackageError) as exc:
        importer.import_package(_build_zip(files), sid, "alice")
    assert exc.value.code == "bad_mime"
    assert exc.value.detail["path"] == "images/chat-1.jpg"
