"""TTS 多角色对话合成测试 — 见 docs/Qwen3-TTS_MultiSpeaker_Dialogue_Guide.md。

覆盖范围(与用户对齐的 G 节):
  ① parse_asr_json 校验 + 预览生成(正常 + 错误)
  ② synthesize 端到端:monkeypatch _get_model + sys.modules fake numpy/soundfile
  ③ 单段 _synthesize_one_segment 抛异常 → 回退静音 + metadata 写入
  ④ jobs.metadata_json / kind 迁移路径(临时 sqlite,旧 schema → _ensure_columns)

环境里没装 numpy / soundfile / qwen_tts / torch / scipy — 测试通过 sys.modules
注入 fake 避开真依赖,CI 不需要 GPU。
"""

from __future__ import annotations

import json
import sqlite3
import sys
import types

import pytest

from app import db, tts_service
from app.storage import EXT_AUDIO_WAV


# ---------- fixtures ----------

@pytest.fixture(autouse=True)
def isolated_app(tmp_path, monkeypatch):
    """每例:DB + STORAGE 指到 tmp_path;queue state 不在测试范围;模型单例重置。"""
    test_db = tmp_path / "test.db"
    test_storage = tmp_path / "storage"
    test_storage.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(db, "DB_PATH", test_db)
    from app import storage as storage_pkg
    monkeypatch.setattr(storage_pkg, "STORAGE_DIR", test_storage)
    db.init_schema()
    tts_service.reset_model_for_tests()
    yield test_storage
    tts_service.reset_model_for_tests()


# ---------- numpy / soundfile sys.modules fake ----------

class _FakeNumpyArray:
    """最小 numpy 替身:支持 len / astype。"""

    def __init__(self, n: int):
        self.n = int(n)

    def __len__(self) -> int:
        return self.n

    def astype(self, dtype):  # noqa: ARG002 — 实际不转换,fake
        return self


class _FakeNumpy:
    float32 = "float32"

    @staticmethod
    def zeros(n, dtype=None):  # noqa: ARG001
        return _FakeNumpyArray(int(n))

    @staticmethod
    def asarray(x, dtype=None):  # noqa: ARG001
        if isinstance(x, _FakeNumpyArray):
            return x
        try:
            return _FakeNumpyArray(len(x))
        except TypeError:
            return _FakeNumpyArray(0)

    @staticmethod
    def concatenate(arrays):
        return _FakeNumpyArray(sum(len(a) for a in arrays))


def _fake_sf_write(path, data, sr):
    """最小 soundfile 替身:用 stdlib wave 写真 wav(全零采样,只为占位)。"""
    import wave

    n = max(0, len(data))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(int(sr))
        w.writeframes(b"\x00\x00" * n)


@pytest.fixture
def fake_numpy_soundfile(monkeypatch):
    """注入 fake numpy + soundfile 到 sys.modules(venv 没装)。"""
    np_mod = types.ModuleType("numpy")
    np_mod.zeros = _FakeNumpy.zeros
    np_mod.asarray = _FakeNumpy.asarray
    np_mod.concatenate = _FakeNumpy.concatenate
    np_mod.float32 = _FakeNumpy.float32
    monkeypatch.setitem(sys.modules, "numpy", np_mod)
    sf_mod = types.ModuleType("soundfile")
    sf_mod.write = _fake_sf_write
    monkeypatch.setitem(sys.modules, "soundfile", sf_mod)
    return np_mod, sf_mod


# ---------- helpers ----------

def _make_asr_file(user_id: str, session_id: str, segments: list[dict]) -> str:
    """写 ASR JSON + 落 files 表,返回 file_id。

    不走 storage.save_upload_bytes —— 它的 EXT_TO_MIME 白名单不含 'json'
    (这是 /api/upload 的设计:上传图片素材),ASR 文件由 /api/tts/import-asr
    走 save_upload_bytes 之外的直接 path 写盘(见 main.py)。
    """
    import uuid as _uuid

    from app.storage import upload_path

    payload = json.dumps({"segments": segments}, ensure_ascii=False).encode()
    file_id = _uuid.uuid4().hex[:26]
    target = upload_path(user_id, session_id, file_id, "json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    db.insert_file(
        file_id=file_id, session_id=session_id, user_id=user_id,
        kind="asr", ext="json", size=len(payload), content_type="application/json",
    )
    return file_id


class _FakeModel:
    """替身 Qwen3-TTS 模型,记录调用 + 返回 1 秒静音 @ 24kHz。"""

    def __init__(self):
        self.calls: list[dict] = []

    def generate_custom_voice(self, *, text, language, speaker, instruct=None):
        self.calls.append({
            "text": text, "language": language,
            "speaker": speaker, "instruct": instruct,
        })
        return ([_FakeNumpy.zeros(24000)], 24000)


# ============================================================================
# ① ASR 解析
# ============================================================================

def test_parse_asr_json_ok_mixed():
    """正常混合:系统段 + 多角色段 + 首条非空非系统段预览。"""
    payload = {
        "segments": [
            {"speaker_id": "__system__", "start_ms": 0, "end_ms": 500, "text": "欢迎"},
            {"speaker_id": "laoyan", "start_ms": 500, "end_ms": 3500,
             "text": "今天的猪价怎么样", "speaker": "老严"},
            {"speaker_id": "xiaoqiang", "start_ms": 3500, "end_ms": 6500,
             "text": "跌了不少", "speaker": "小强"},
        ]
    }
    parsed = tts_service.parse_asr_json(payload)
    assert parsed["segments_count"] == 3
    assert parsed["total_duration_ms"] == 6500
    assert parsed["speakers"] == ["laoyan", "xiaoqiang"]  # 排序 + 剔除系统段
    assert parsed["speaker_segments"] == {"laoyan": 1, "xiaoqiang": 1}
    assert parsed["first_segment_preview"] == {
        "start_ms": 500, "end_ms": 3500, "text": "今天的猪价怎么样",
    }


def test_parse_asr_json_first_preview_skips_empty():
    """空文本不占位 first_segment_preview。"""
    payload = {
        "segments": [
            {"speaker_id": "laoyan", "start_ms": 0, "end_ms": 1000, "text": ""},
            {"speaker_id": "xiaoqiang", "start_ms": 1000, "end_ms": 2000,
             "text": "  "},
            {"speaker_id": "abin", "start_ms": 2000, "end_ms": 3000,
             "text": "有事说事"},
        ]
    }
    parsed = tts_service.parse_asr_json(payload)
    assert parsed["first_segment_preview"] == {
        "start_ms": 2000, "end_ms": 3000, "text": "有事说事",
    }


def test_parse_asr_json_rejects_non_dict():
    with pytest.raises(tts_service.AsrParseError, match="must be an object"):
        tts_service.parse_asr_json([])


def test_parse_asr_json_rejects_empty_segments():
    with pytest.raises(tts_service.AsrParseError, match="non-empty 'segments'"):
        tts_service.parse_asr_json({"segments": []})


def test_parse_asr_json_rejects_missing_field():
    with pytest.raises(tts_service.AsrParseError, match="missing required field"):
        tts_service.parse_asr_json({"segments": [{"start_ms": 0, "end_ms": 1}]})


def test_parse_asr_json_rejects_non_int_timestamp():
    with pytest.raises(tts_service.AsrParseError, match="timestamps must be integers"):
        tts_service.parse_asr_json({"segments": [{
            "speaker_id": "laoyan", "start_ms": "x", "end_ms": 100, "text": "y",
        }]})


# ============================================================================
# ② synthesize 端到端:fake 模型 + fake numpy/soundfile
# ============================================================================

@pytest.mark.asyncio
async def test_synthesize_end_to_end_with_fake_model(fake_numpy_soundfile, isolated_app):
    """✅ ASR + 单例 fake 模型 + soundfile 替身 → 产物 wav 落盘 + meta.json 空失败列表。

    验证点:
      1) wav 落到 outputs/{job_id}.wav,size > 0
      2) meta.json 存在,failed_segments 为空
      3) 进度回调 1/3/96/99 + 段循环至少 1 次
      4) 模型被调过(系统段走静音不进 model),speaker 用了默认映射
    """
    from app.storage import output_path

    user_id = "u-tts"
    db.upsert_user(user_id)
    sess = db.create_session(user_id, "s-tts-1", title="tts")
    sid = sess["id"]

    segments = [
        {"speaker_id": "__system__", "start_ms": 0, "end_ms": 500, "text": "欢迎"},
        {"speaker_id": "laoyan", "start_ms": 500, "end_ms": 2500,
         "text": "今天的猪价怎么样", "speaker": "老严"},
        {"speaker_id": "xiaoqiang", "start_ms": 2500, "end_ms": 4500,
         "text": "跌了不少", "speaker": "小强"},
    ]
    asr_file_id = _make_asr_file(user_id, sid, segments)

    fake_model = _FakeModel()

    async def fake_get_model(model_path=None):
        return fake_model

    tts_service._get_model = fake_get_model  # type: ignore[assignment]

    job_id = "job-tts-1"
    progress_calls: list[int] = []

    async def progress_cb(p: int):
        progress_calls.append(p)

    wav_path = await tts_service.synthesize(
        job_id=job_id, user_id=user_id, session_id=sid,
        config={"asr_file_id": asr_file_id, "language": "Chinese"},
        progress_cb=progress_cb,
    )

    # 1) wav 落盘
    expected = output_path(user_id, sid, job_id, EXT_AUDIO_WAV)
    assert wav_path == expected
    assert wav_path.is_file()
    assert wav_path.stat().st_size > 0

    # 2) meta.json:0 失败
    meta_path = wav_path.with_name(f"{wav_path.stem}.meta.json")
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta == {"failed_segments": []}

    # 3) 进度回调
    assert len(progress_calls) >= 5
    assert progress_calls[0] == 1
    assert progress_calls[-1] == 99

    # 4) 模型调用次数:系统段不进 model,所以 2 次
    assert len(fake_model.calls) == 2
    speakers_used = {c["speaker"] for c in fake_model.calls}
    # 内置默认:laoyan→Ryan, xiaoqiang→Ethan
    assert speakers_used == {"Ryan", "Ethan"}


# ============================================================================
# ③ 单段失败回退静音 + metadata
# ============================================================================

@pytest.mark.asyncio
async def test_synthesize_segment_failure_falls_back_to_silence(
    fake_numpy_soundfile, isolated_app,
):
    """✅ 第 N 段 _synthesize_one_segment 抛异常 → 整段 wav 仍落盘 + meta.json 记失败明细。

    校验:fail list 长度=1,speaker/speaker_id/text/reason 与被炸段对得上。
    """
    user_id = "u-tts"
    db.upsert_user(user_id)
    sess = db.create_session(user_id, "s-tts-2", title="tts")
    sid = sess["id"]

    segments = [
        {"speaker_id": "laoyan", "start_ms": 0, "end_ms": 1000, "text": "第一段"},
        {"speaker_id": "xiaoqiang", "start_ms": 1000, "end_ms": 2000,
         "text": "第二段"},  # 这段会被炸
        {"speaker_id": "abin", "start_ms": 2000, "end_ms": 3000, "text": "第三段"},
    ]
    asr_file_id = _make_asr_file(user_id, sid, segments)

    async def fake_get_model(model_path=None):
        return _FakeModel()

    tts_service._get_model = fake_get_model  # type: ignore[assignment]

    original = tts_service._synthesize_one_segment

    async def selective(model, *, text, speaker, instruct, language, target_sr):
        if speaker == "Ethan":
            raise RuntimeError("simulated inference failure")
        return await original(
            model, text=text, speaker=speaker, instruct=instruct,
            language=language, target_sr=target_sr,
        )

    tts_service._synthesize_one_segment = selective  # type: ignore[assignment]

    job_id = "job-tts-2"

    async def progress_cb(p: int):
        pass

    wav_path = await tts_service.synthesize(
        job_id=job_id, user_id=user_id, session_id=sid,
        config={"asr_file_id": asr_file_id}, progress_cb=progress_cb,
    )

    assert wav_path.is_file() and wav_path.stat().st_size > 0
    meta_path = wav_path.with_name(f"{wav_path.stem}.meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert len(meta["failed_segments"]) == 1
    fail = meta["failed_segments"][0]
    # 默认映射 xiaoqiang→Ethan
    assert fail["speaker"] == "Ethan"
    assert fail["speaker_id"] == "xiaoqiang"
    assert "simulated inference failure" in fail["reason"]
    assert "第二段" in fail["text"]


# ============================================================================
# ④ jobs.metadata_json / kind 迁移路径
# ============================================================================

def test_jobs_schema_migration_adds_kind_and_metadata_json(tmp_path, monkeypatch):
    """✅ 老 jobs 表(无 kind / metadata_json)经 _ensure_columns 后两列可用。

    路径:
      ① 旧 SCHEMA 建 jobs(无 kind / metadata_json)
      ② db.init_schema() 触发迁移
      ③ 旧行 kind 默认 'render',metadata_json NULL
      ④ 新行 kind='tts' + metadata_json round-trip
      ⑤ finish_job 落 metadata_json 也能读回 dict
    """
    test_db = tmp_path / "legacy-tts.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)

    legacy = sqlite3.connect(str(test_db))
    try:
        legacy.executescript(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                created_at REAL NOT NULL
            );
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                title TEXT, created_at REAL NOT NULL, last_active_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE files (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                user_id TEXT NOT NULL, kind TEXT NOT NULL, ext TEXT NOT NULL,
                size INTEGER NOT NULL, content_type TEXT, created_at REAL NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                FOREIGN KEY (user_id)    REFERENCES users(id)
            );
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                user_id TEXT NOT NULL, status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                config_json TEXT NOT NULL,
                output_ext TEXT NOT NULL DEFAULT 'mp4',
                error TEXT, created_at REAL NOT NULL, finished_at REAL
            );
            """
        )
        legacy.commit()
    finally:
        legacy.close()

    # 触发迁移
    db.init_schema()

    # PRAGMA 验证两列已加
    cols = {r[1] for r in sqlite3.connect(str(test_db))
            .execute("PRAGMA table_info(jobs)").fetchall()}
    assert "kind" in cols and "metadata_json" in cols

    # 旧行 kind 默认 'render',metadata_json 默认 NULL
    db.upsert_user("u-leg")
    db.create_session("u-leg", "s-leg")
    db.insert_job(job_id="j-old", session_id="s-leg", user_id="u-leg",
                  config={"scene": {}})
    old_row = db.get_job("j-old")
    assert old_row["kind"] == "render"
    assert old_row["metadata_json"] is None

    # 新行 kind='tts' + metadata_json round-trip
    db.insert_job(
        job_id="j-new", session_id="s-leg", user_id="u-leg",
        config={"asr_file_id": "x"}, kind="tts",
        metadata_json=json.dumps(
            {"failed_segments": [{"idx": 0, "reason": "x"}]}
        ),
    )
    new_row = db.get_job("j-new")
    assert new_row["kind"] == "tts"
    assert new_row["metadata_json"] == {
        "failed_segments": [{"idx": 0, "reason": "x"}],
    }

    # finish_job 落 metadata_json 也能被读回(验证 fix:to_thread 把 kwarg 传过去了)
    db.finish_job("j-new", "done", None,
                  metadata_json=json.dumps(
                      {"failed_segments": [{"idx": 2, "reason": "timeout"}]}
                  ))
    final = db.get_job("j-new")
    assert final["status"] == "done"
    assert final["metadata_json"]["failed_segments"][0]["idx"] == 2


def test_jobs_kind_and_output_ext_whitelist():
    """✅ 不在白名单的 kind / output_ext 直接 ValueError,免得下游 500。"""
    db.upsert_user("u")
    db.create_session("u", "s-wh")
    with pytest.raises(ValueError, match="unsupported job kind"):
        db.insert_job(
            job_id="j1", session_id="s-wh", user_id="u", config={},
            kind="bogus",
        )
    with pytest.raises(ValueError, match="unsupported output_ext"):
        db.insert_job(
            job_id="j2", session_id="s-wh", user_id="u", config={},
            output_ext="mp3", kind="tts",
        )
    # 正确用例:output_ext='wav' + kind='tts'
    db.insert_job(
        job_id="j3", session_id="s-wh", user_id="u", config={},
        output_ext=EXT_AUDIO_WAV, kind="tts",
    )
    assert db.get_job("j3")["output_ext"] == "wav"
    assert db.get_job("j3")["kind"] == "tts"


# ============================================================================
# ⑤ /api/tts/import-asr + /api/tts 端点(2025-Q3 回归测试,钉死 Bug 1 / Bug 2)
# ============================================================================
#
# 这两个用例补上单元测试绕过的"路由 + 文件落盘"组合,确保 save_upload_bytes
# 接受 json(Bug 1)与 /api/tts 校验顺序(Bug 2)以后再也不退化。

import io  # noqa: E402 — 放在这里方便上面看整体结构


def _png_bytes() -> bytes:
    """最小可识别 PNG,用于 /api/upload 的 avatar kind。"""
    return bytes.fromhex(
        "89504e470d0a1a0a"          # PNG signature
        "00000001"                  # IHDR length
        "00000001000000010802000000" # IHDR chunk body (1x1)
        "907753de"                  # IHDR CRC
        "00000000"                  # IEND length
        "49454e44ae426082"          # IEND chunk
    )


@pytest.fixture
def client():
    """端到端用 TestClient。不带 `with` — lifespan 不触发,workers 不起,只跑路由。"""
    from fastapi.testclient import TestClient

    from app import main

    return TestClient(main.app)


def _h(uid: str) -> dict[str, str]:
    return {"X-User-Id": uid}


def test_import_asr_endpoint_happy_path(client, isolated_app):
    """✅ POST /api/tts/import-asr(form: session_id + JSON file) → 200 + 完整预览字段。

    钉死 Bug 1:save_upload_bytes 必须接受 ext="json",否则这里会 500。
    之前单元测试自己写文件绕过了 save_upload_bytes,所以这个 bug 漏到了端点层。
    """
    # 建 alice 的 session
    r = client.post("/api/sessions", headers=_h("alice"))
    assert r.status_code == 201
    sid = r.json()["id"]

    asr_payload = json.dumps({
        "segments": [
            {"speaker_id": "__system__", "start_ms": 0, "end_ms": 500, "text": "欢迎"},
            {"speaker_id": "laoyan", "start_ms": 500, "end_ms": 2500,
             "text": "今天的猪价怎么样", "speaker": "老严"},
            {"speaker_id": "xiaoqiang", "start_ms": 2500, "end_ms": 4500,
             "text": "跌了不少", "speaker": "小强"},
        ]
    }, ensure_ascii=False).encode()

    r = client.post(
        "/api/tts/import-asr",
        headers=_h("alice"),
        data={"session_id": sid},
        files={"file": ("asr.json", io.BytesIO(asr_payload), "application/json")},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["segments_count"] == 3
    assert body["total_duration_ms"] == 4500
    assert sorted(body["speakers"]) == ["laoyan", "xiaoqiang"]
    assert body["speaker_segments"] == {"laoyan": 1, "xiaoqiang": 1}
    assert body["first_segment_preview"] == {
        "start_ms": 500, "end_ms": 2500, "text": "今天的猪价怎么样",
    }
    assert body["file_id"]
    assert body["url"] == f"/api/files/{body['file_id']}"

    # files 表确实落了 kind="asr"
    row = db.get_file(body["file_id"])
    assert row is not None
    assert row["kind"] == "asr"
    assert row["ext"] == "json"
    assert row["user_id"] == "alice"
    assert row["session_id"] == sid


def test_import_asr_endpoint_rejects_non_asr_file_kind(client, isolated_app):
    """✅ POST /api/tts 拿到一个 kind="avatar" 的 file_id → 400 + 'file kind must be asr'。

    钉死 Bug 2 的一部分:就算用户绕过 /api/tts/import-asr 直接拿上传素材当
    ASR 提交,服务端必须以 400 拒绝,不能默默跑出奇怪的合成结果。

    顺带校验:Bug 2 修完后,kind 校验应该在 TTS_MODEL_PATH 校验之前 ——
    否则会先返回 503。这里通过 mock tts_service.TTS_MODEL_PATH 为空 + 一个
    错误的 file_id 验证:400 不是 503。
    """
    import uuid as _uuid

    from app.storage import upload_path

    # 1) 手工造一个 kind="avatar" / ext="png" 的 files 行(不走 /api/upload 减少依赖)
    db.upsert_user("alice")
    db.create_session("alice", "s-bug2")
    avatar_fid = _uuid.uuid4().hex[:26]
    target = upload_path("alice", "s-bug2", avatar_fid, "png")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_png_bytes())
    db.insert_file(
        file_id=avatar_fid, session_id="s-bug2", user_id="alice",
        kind="avatar", ext="png", size=len(_png_bytes()),
        content_type="image/png",
    )

    # 2) TTS_MODEL_PATH 临时清空,这样如果顺序错了就会先 503
    from app import tts_service as tts_mod
    original_model_path = tts_mod.TTS_MODEL_PATH
    tts_mod.TTS_MODEL_PATH = ""
    try:
        r = client.post(
            "/api/tts",
            headers=_h("alice"),
            json={"session_id": "s-bug2", "asr_file_id": avatar_fid},
        )
    finally:
        tts_mod.TTS_MODEL_PATH = original_model_path

    # 期望 400 而不是 503 — kind 校验在 TTS_MODEL_PATH 之前
    assert r.status_code == 400, r.text
    assert "must be 'asr'" in r.json()["detail"]


# ============================================================================
# ⑥ build_asr_from_dsl + /api/tts/from-job + /api/tts/by-source/{job_id}
# (时间码页「生成语音」按钮闭环,2025-Q3 增量)
# ============================================================================


def _make_dsl(messages: list[dict]) -> dict:
    """最小可用 VideoDSL dict(供 main.from-job 端点 + db 直接入库用)。"""
    return {
        "schema_version": "1.0",
        "kind": "chat",
        "template": "cyberpunk",
        "scene": {
            "mode": "group",
            "title": "测试对话",
            "background": "#0a0a12",
            "background_image_url": None,
            "background_visible": True,
            "duration_ms": None,
            "opacity": 1.0,
            "intro_effect": "none",
            "style_theme": "cyberpunk",
            "intent": "short_video_drama",
            "intent_acknowledged": True,
            "participants": [
                {"id": "alice", "name": "老严", "avatar_url": None, "persona": ""},
                {"id": "bob", "name": "小强", "avatar_url": None, "persona": ""},
            ],
            "messages": messages,
            "watermark": {"text": "AI", "badge_style": "neon"},
        },
        "transparent": False,
        "transparent_format": None,
    }


def _messages_4() -> list[dict]:
    """4 条消息:2 text + 1 sys + 1 image(image 应被跳过)。"""
    return [
        {"sender_id": "alice", "kind": "text", "text": "今天猪价怎么样",
         "image_url": None, "video_url": None, "cover_url": None,
         "duration": None, "delay_ms": 1500, "align": None, "reply_to": None},
        {"sender_id": "bob", "kind": "text", "text": "跌了不少",
         "image_url": None, "video_url": None, "cover_url": None,
         "duration": None, "delay_ms": 1500, "align": None, "reply_to": None},
        {"sender_id": "__system__", "kind": "sys", "text": "中场休息",
         "image_url": None, "video_url": None, "cover_url": None,
         "duration": None, "delay_ms": 1500, "align": None, "reply_to": None},
        {"sender_id": "alice", "kind": "image", "text": None,
         "image_url": "/uploads/foo.png", "video_url": None, "cover_url": None,
         "duration": None, "delay_ms": 1500, "align": None, "reply_to": None},
    ]


def test_build_asr_from_dsl_basic():
    """✅ build_asr_from_dsl:4 条消息(text×2 + sys×1 + image×1)→ 3 段,image 被跳过。"""
    from app.dsl import VideoDSL
    from app.models import Message, Participant

    # 走 Message / Participant 模型校验一遍,让 VideoDSL.model_validate 通过
    participants = [
        Participant(id="alice", name="老严", avatar_url=None, persona=""),
        Participant(id="bob", name="小强", avatar_url=None, persona=""),
    ]
    messages = []
    for d in _messages_4():
        messages.append(Message(
            sender_id=d["sender_id"], kind=d["kind"], text=d["text"],
            image_url=d["image_url"], video_url=d["video_url"],
            cover_url=d["cover_url"], duration=d["duration"],
            delay_ms=d["delay_ms"], align=d["align"], reply_to=d["reply_to"],
        ))
    # VideoDSL.model_validate 走 dict 路径更省事
    dsl = VideoDSL.model_validate(_make_dsl(_messages_4()))

    asr = tts_service.build_asr_from_dsl(dsl)
    assert isinstance(asr, dict) and "segments" in asr
    segs = asr["segments"]
    # image 被跳过 → 只剩 3 段(text × 2 + sys × 1)
    assert len(segs) == 3

    # speaker_id 原值透传
    assert [s["speaker_id"] for s in segs] == ["alice", "bob", "__system__"]
    # speaker 由 participant.name 解析(sys 找不到 → None)
    assert segs[0]["speaker"] == "老严"
    assert segs[1]["speaker"] == "小强"
    assert segs[2]["speaker"] is None

    # start_ms / end_ms 单调递增 + 差值 = delay_ms(1500)
    cumulative = 0
    for seg, msg in zip(segs, _messages_4()[:3]):
        assert seg["start_ms"] == cumulative
        assert seg["end_ms"] - seg["start_ms"] == msg["delay_ms"]
        cumulative = seg["end_ms"]
    assert cumulative == 4500  # 3 × 1500

    # 能被 parse_asr_json 直接吃 → speakers / first_segment_preview 等正常
    parsed = tts_service.parse_asr_json(asr)
    assert parsed["segments_count"] == 3
    assert parsed["total_duration_ms"] == 4500
    assert parsed["speakers"] == ["alice", "bob"]
    assert parsed["speaker_segments"] == {"alice": 1, "bob": 1}
    assert parsed["first_segment_preview"]["text"] == "今天猪价怎么样"


def test_from_job_endpoint_happy_path(
    client, fake_numpy_soundfile, isolated_app, monkeypatch,
):
    """✅ POST /api/tts/from-job { job_id: <done render> } → 202 + tts_job_id,
    并在 jobs / files 表里留下可追溯的痕迹。

    mock _get_model 返回 fake 模型 — CI 不需要 GPU;
    fake 路径里不入队也不跑 _process_job,只验证 API 层副作用(入 jobs / files)。
    """
    from app import tts_service as tts_mod

    # TTS_MODEL_PATH 默认空,会被 main.from-job 的 TTS 可用性检查挡掉;测试临时填一个
    # 假路径,fake 模型会替掉 _get_model,所以这个路径实际不会被读。
    monkeypatch.setattr(tts_mod, "TTS_MODEL_PATH", "/fake/qwen3-tts-path")

    # monkeypatch _get_model 让 enqueue_tts 后续真要跑也不会炸
    async def fake_get_model(model_path=None):
        return _FakeModel()
    tts_mod._get_model = fake_get_model  # type: ignore[assignment]

    # 1) 建 alice + session + 一个 done 状态的 render job(装一份能过 VideoDSL 校验的 config)
    user_id = "alice"
    db.upsert_user(user_id)
    sess = db.create_session(user_id, "s-fromjob")
    sid = sess["id"]
    config = _make_dsl(_messages_4())
    render_job = db.insert_job(
        job_id="r-1", session_id=sid, user_id=user_id,
        config=config, output_ext="mp4",
    )
    db.update_job_status("r-1", "running", 50)
    db.finish_job("r-1", "done", None)

    # 2) 调 /api/tts/from-job
    r = client.post(
        "/api/tts/from-job",
        headers=_h(user_id),
        json={"job_id": "r-1"},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["tts_job_id"]

    # 3) jobs 表里多一条 kind="tts" 的记录,config_json.source_job_id 反查到原 render
    tts_row = db.get_job(body["tts_job_id"])
    assert tts_row is not None
    assert tts_row["kind"] == "tts"
    assert tts_row["user_id"] == user_id
    assert tts_row["session_id"] == sid
    assert tts_row["output_ext"] == EXT_AUDIO_WAV
    cfg = tts_row["config"]
    assert cfg["source_job_id"] == "r-1"
    assert cfg["role_map"] == {} and cfg["instructs"] == {}
    # asr_file_id 应指向刚入库的 kind="asr" 文件
    asr_file_id = cfg["asr_file_id"]
    f_row = db.get_file(asr_file_id)
    assert f_row is not None
    assert f_row["kind"] == "asr"
    assert f_row["ext"] == "json"
    assert f_row["user_id"] == user_id
    assert f_row["session_id"] == sid


def test_by_source_returns_latest_tts(client, isolated_app):
    """✅ GET /api/tts/by-source/{job_id} 返回 created_at 最新的那条 TTS 任务。

    模拟时间码页持久化:同一 render 任务派生过 2 次 TTS,前端应看到最近的那次。
    """
    user_id = "alice"
    db.upsert_user(user_id)
    db.create_session(user_id, "s-bysrc")
    sid = "s-bysrc"

    # 公共 render job(只用来当 source_job_id,本测试不直接用)
    db.insert_job(
        job_id="r-src", session_id=sid, user_id=user_id,
        config={}, output_ext="mp4",
    )

    # 2 条 TTS 子任务:第一条老,第二条新
    import time
    cfg_old = {
        "asr_file_id": "x1", "source_job_id": "r-src",
        "role_map": {}, "instructs": {},
    }
    cfg_new = {
        "asr_file_id": "x2", "source_job_id": "r-src",
        "role_map": {}, "instructs": {},
    }
    db.insert_job(
        job_id="t-old", session_id=sid, user_id=user_id,
        config=cfg_old, output_ext=EXT_AUDIO_WAV, kind="tts",
    )
    time.sleep(0.01)  # 确保 created_at 不撞
    db.insert_job(
        job_id="t-new", session_id=sid, user_id=user_id,
        config=cfg_new, output_ext=EXT_AUDIO_WAV, kind="tts",
    )

    r = client.get("/api/tts/by-source/r-src", headers=_h(user_id))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body is not None
    assert body["tts_job_id"] == "t-new"
    assert body["status"] == "queued"
    assert body["output_url"] is None
    assert body["error"] is None
    assert body["metadata_json"] is None

    # 找别的 source_job_id / 别的 user → 200 + null
    r2 = client.get("/api/tts/by-source/no-such-source", headers=_h(user_id))
    assert r2.status_code == 200
    assert r2.json() is None

    # 跨用户:alice 的 tts 任务对 bob 不可见
    db.upsert_user("bob")
    r3 = client.get("/api/tts/by-source/r-src", headers=_h("bob"))
    assert r3.status_code == 200
    assert r3.json() is None


@pytest.mark.asyncio
async def test_get_model_rejects_nonexistent_path():
    """非目录路径必须在抢锁前被拒,避免把 Windows 路径冒号喂进 HF repo_id_validator。"""
    # 前面 synthesize 测试直接 tts_service._get_model = fake_get_model 覆盖了模块字典,
    # reload 一次把模块级 dict 还原,确保这里测的是真实 _get_model。
    import importlib
    importlib.reload(tts_service)
    with pytest.raises(RuntimeError, match="is not an existing directory"):
        await tts_service._get_model(model_path="D:\\nonexistent\\fake-model-path")