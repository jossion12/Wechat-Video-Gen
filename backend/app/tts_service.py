"""Qwen3-TTS 多角色对话合成 — 见 docs/Qwen3-TTS_MultiSpeaker_Dialogue_Guide.md。

架构角色:
- 与 recorder.render_video 平级的 pipeline 节点;queue._process_job 按 jobs.kind 分发。
- 单例模型 + asyncio.Lock(同时承担"懒加载保护"和"GPU 串行访问"):
  同进程同一时刻只一个 TTS 推理,避免 GPU 抢资源。
- synthesize(job_id, user_id, session_id, config, progress_cb) 签名与
  recorder.render_video 对齐(5 个参数,返回 wav 路径)。
- 单段 asyncio.wait_for 包裹推理,超时 / 抛错回退静音 + 写
  outputs/{job_id}.meta.json;_process_job 读取 meta.json 后调 finish_job 落库。
- TTS_VOICE_CONFIG 指向的文件不存在时回退内置默认 + logger.warning,不抛异常。

不在本期范围(与用户确认):
- 不做 wav 嵌入视频(独立 wav 成品,见 docs)。
- 不做 VoiceDesign / VoiceClone(只用 CustomVoice 的内置 speaker)。
- 不做任务级重试,失败段只写 metadata。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.storage import EXT_AUDIO_WAV, output_path

logger = logging.getLogger("tts_service")

ProgressCallback = Callable[[int], Awaitable[None]]

# ---------- 配置(env) ----------

TTS_ENABLED = os.getenv("TTS_ENABLED", "true").strip().lower() in ("1", "true", "yes")
TTS_MODEL_PATH = os.getenv("TTS_MODEL_PATH", "").strip()
TTS_DEVICE = os.getenv("TTS_DEVICE", "cuda:0").strip()
TTS_DTYPE = os.getenv("TTS_DTYPE", "bfloat16").strip()
TTS_TARGET_SR = int(os.getenv("TTS_TARGET_SR", "24000"))
TTS_LANGUAGE = os.getenv("TTS_LANGUAGE", "Chinese").strip()
TTS_INFERENCE_TIMEOUT_S = float(os.getenv("TTS_INFERENCE_TIMEOUT_S", "120"))
TTS_VOICE_CONFIG = os.getenv("TTS_VOICE_CONFIG", "").strip()

# ---------- 内置默认音色(与 backend/config/tts_voices.json.example 同步) ----------

_BUILTIN_VOICE_CONFIG: dict[str, Any] = {
    "default_speakers": {
        "laoyan": "Ryan",
        "xiaoqiang": "Ethan",
        "jingjie": "Vivian",
        "abin": "Adam",
    },
    "default_instructs": {
        "laoyan": "用沉稳、权威的语气,像资深农业分析师一样说话",
        "xiaoqiang": "用略带焦虑、朴实的语气,像基层养殖户一样说话",
        "jingjie": "用冷静、理性的语气,像数据研究员一样说话",
        "abin": "用干脆、直接的语气,像行业老手一样说话",
    },
    "available_speakers": ["Ryan", "Ethan", "Vivian", "Adam", "Emma", "Olivia"],
}


def _load_voice_config() -> dict[str, Any]:
    """启动时一次性加载音色配置;文件缺失 / 解析失败回退内置默认。

    与用户约定的契约:TTS_VOICE_CONFIG 指向的文件不存在不算错,只 logger.warning,
    服务继续启动(这样未配置 TTS 的环境也能起 backend,只是 /api/tts/* 走 503 路径)。
    """
    if not TTS_VOICE_CONFIG:
        return _BUILTIN_VOICE_CONFIG
    path = Path(TTS_VOICE_CONFIG)
    if not path.is_file():
        logger.warning(
            "TTS_VOICE_CONFIG=%s not found, falling back to built-in defaults",
            TTS_VOICE_CONFIG,
        )
        return _BUILTIN_VOICE_CONFIG
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — 配置坏掉也只警告,不影响启动
        logger.warning(
            "TTS_VOICE_CONFIG=%s parse failed: %s; falling back to built-in defaults",
            TTS_VOICE_CONFIG, exc,
        )
        return _BUILTIN_VOICE_CONFIG
    if not isinstance(data, dict):
        logger.warning(
            "TTS_VOICE_CONFIG=%s root must be an object; falling back to built-in defaults",
            TTS_VOICE_CONFIG,
        )
        return _BUILTIN_VOICE_CONFIG
    return data


_voice_config: dict[str, Any] = _load_voice_config()


def get_voice_config() -> dict[str, Any]:
    """返回启动时加载的音色配置(GET /api/tts/voices 用)。"""
    return _voice_config


# ---------- 单例模型 ----------

_model: Any = None
_model_path: str | None = None
_model_lock = asyncio.Lock()


def _resolve_dtype() -> Any:
    """把字符串 dtype 映射成 torch.dtype;失败回退 bfloat16。"""
    try:
        import torch  # type: ignore
    except ImportError:
        return None
    return {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
        "float32": torch.float32,
    }.get(TTS_DTYPE, torch.bfloat16)


async def _get_model(model_path: str | None = None) -> Any:
    """懒加载 + 单例:同一模型路径复用,路径变了重新加载。

    锁语义:
      - 第一次调用:无 _model → 抢锁 → 加载 → 缓存 → 释放锁;
      - 后续调用:_model 已就绪 → 抢锁 → 立即返回(几乎不阻塞);
      - 不同 worker 同时第一次调用:第一个拿到锁去加载,其余等锁 → 拿到后 _model
        已存在 → 命中 fast path → 立即释放。

    这个锁同时承担两件事 ——「保护首次加载」和「序列化后续 GPU 调用」。前者保证
    不会两个并发各起一份 1.7B 模型;后者保证 model.generate_custom_voice 同一时刻
    只有一个在跑(Qwen3-TTS 的 generate 是 blocking torch 调用,丢进 to_thread 但
    锁不释放,其他 worker 就在 lock.acquire() 上排队)。
    """
    global _model, _model_path
    target = (model_path or TTS_MODEL_PATH).strip()
    if not target:
        raise RuntimeError(
            "TTS model path not configured: set TTS_MODEL_PATH env or pass model_path"
        )

    # 本地路径强校验 —— 避免把 Windows 路径里的 ':' / 错字符串喂进 HF repo_id_validator
    # (qwen_tts 内部某条路径会在 isdir 判定之前先调 repo_id_validator,本地路径被错认为 repo_id)。
    target_path = Path(target).expanduser().resolve()
    if not target_path.is_dir():
        # 友好诊断:Windows 路径被丢进 Linux 容器(Docker)是常见踩坑,
        # 看见路径里含 ':' 或 '\\' 且当前不是 Windows,直接提示用户怎么改。
        import sys
        looks_like_windows_path = (":" in target or "\\" in target) and sys.platform != "win32"
        if looks_like_windows_path:
            raise RuntimeError(
                f"TTS_MODEL_PATH 看起来是 Windows 路径 ({target!r}),但当前运行在 "
                f"Linux/Docker 容器里。Docker 部署需在 docker-compose.yml 里把宿主模型目录 "
                f"mount 进容器(例如 /d/model/modelscope:/app/tts-models:ro),然后把 .env 的 "
                f"TTS_MODEL_PATH 改成容器内路径(如 /app/tts-models/Qwen3-TTS-12Hz-1.7B-CustomVoice)。"
            )
        raise RuntimeError(
            f"TTS model path is not an existing directory: {target_path}"
        )
    target = str(target_path)

    async with _model_lock:
        if _model is not None and _model_path == target:
            return _model

        from qwen_tts import Qwen3TTSModel  # type: ignore

        dtype = _resolve_dtype()
        logger.info(
            "Loading Qwen3-TTS model from %s (device=%s dtype=%s)",
            target, TTS_DEVICE, TTS_DTYPE,
        )
        loaded = await asyncio.to_thread(
            Qwen3TTSModel.from_pretrained,
            target,
            device_map=TTS_DEVICE,
            dtype=dtype,
            attn_implementation="sdpa",
            local_files_only=True,
        )
        _model = loaded
        _model_path = target
        logger.info("Qwen3-TTS model loaded")
        return _model


def reset_model_for_tests() -> None:
    """测试 hook:重置单例,方便 monkeypatch _get_model 或换路径。"""
    global _model, _model_path
    _model = None
    _model_path = None


async def get_supported_speakers(model_path: str | None = None) -> list[str]:
    """实际从模型问一次可用 speaker 列表。模型未加载则触发加载;失败抛 RuntimeError。

    主入口(/api/tts/voices)调用,失败时上层转 503 给运维排查。
    """
    model = await _get_model(model_path)
    try:
        speakers = model.get_supported_speakers()
    except Exception as exc:
        raise RuntimeError(f"get_supported_speakers failed: {exc}") from exc
    return [str(s) for s in speakers]


# ---------- ASR 解析 ----------

class AsrParseError(ValueError):
    """ASR JSON 结构不合法时抛。"""


def parse_asr_json(data: Any) -> dict[str, Any]:
    """校验 ASR JSON 并返回摘要。

    输入约定(见 docs/Qwen3-TTS_MultiSpeaker_Dialogue_Guide.md):
      {
        "segments": [
          {"speaker_id": "laoyan", "speaker": "老严", "text": "...",
           "start_ms": 0, "end_ms": 3291},
          ...
        ]
      }

    返回:
      {
        "segments": [原数组,透传],
        "segments_count": int,
        "total_duration_ms": int(= max(end_ms)),
        "speakers": [去重+排序的 speaker_id,已剔除 __system__],
        "speaker_segments": {speaker_id: 段数},
        "first_segment_preview": {"start_ms","end_ms","text"} | None,
          即第一个非系统且非空的 segment,
      }
    """
    if not isinstance(data, dict):
        raise AsrParseError("ASR JSON must be an object")
    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        raise AsrParseError("ASR JSON must contain non-empty 'segments' array")

    speakers_set: set[str] = set()
    speaker_counts: dict[str, int] = {}
    total_duration_ms = 0
    first_preview: dict[str, Any] | None = None

    for seg in segments:
        if not isinstance(seg, dict):
            raise AsrParseError("each segment must be an object")
        for required in ("speaker_id", "start_ms", "end_ms"):
            if required not in seg:
                raise AsrParseError(f"segment missing required field: {required}")
        sid = str(seg.get("speaker_id", ""))
        try:
            start_ms = int(seg.get("start_ms", 0))
            end_ms = int(seg.get("end_ms", 0))
        except (TypeError, ValueError) as exc:
            raise AsrParseError(f"segment timestamps must be integers: {exc}") from exc
        text = (seg.get("text") or "").strip()
        total_duration_ms = max(total_duration_ms, end_ms)
        if sid and sid != "__system__":
            speakers_set.add(sid)
            speaker_counts[sid] = speaker_counts.get(sid, 0) + 1
            if first_preview is None and text:
                first_preview = {"start_ms": start_ms, "end_ms": end_ms, "text": text}

    return {
        "segments": segments,
        "segments_count": len(segments),
        "total_duration_ms": total_duration_ms,
        "speakers": sorted(speakers_set),
        "speaker_segments": speaker_counts,
        "first_segment_preview": first_preview,
    }


def build_asr_from_dsl(dsl: Any) -> dict[str, Any]:
    """把 DSL 里的对话转成 ASR JSON(供 TTS 合成)。

    输入:VideoDSL(VideoDSL.model_validate(...) 之后的对象)
    输出:parse_asr_json 能直接吃的 dict:
      {
        "segments": [
          {"speaker_id": m.sender_id, "speaker": <participant.name|None>,
           "text": m.text.strip(), "start_ms": int, "end_ms": int},
          ...
        ]
      }

    规则:
      - 只产 text 和 sys 两种 kind 的段,其它(image/video/emoji/timestamp)跳过;
      - speaker_id = m.sender_id(原样透传 DSL 角色 id);
      - speaker = m.sender_id 在 scene.participants 里查到的 name,找不到时为 None
        (parse_asr_json 不强制要求 speaker,这样不会让一段静默失败);
      - 累计 start_ms / end_ms:cumulative_delay + delay_ms,delay_ms<0 当 0;
      - sys 段也按正常段处理(parse_asr_json 会保留,合成时 tts_service.synthesize
        对 sys + 空 text 已经会填静音)。

    与 recorder 里的 delay 计算口径保持一致:每条消息的 start 是上一条结束
    的累计偏移,end = start + max(0, delay_ms);空 text 的 text / sys 段
    会生成对应长度的静音帧,时间轴与视频任务对齐。
    """
    scene = getattr(dsl, "scene", None)
    if scene is None:
        raise AsrParseError("DSL missing 'scene'")

    participants = getattr(scene, "participants", None) or []
    messages = getattr(scene, "messages", None) or []

    name_by_id: dict[str, str] = {}
    for p in participants:
        pid = getattr(p, "id", None)
        pname = getattr(p, "name", None)
        if pid:
            name_by_id[str(pid)] = pname if isinstance(pname, str) and pname else None

    segments: list[dict[str, Any]] = []
    cumulative = 0
    for m in messages:
        kind = getattr(m, "kind", None)
        if kind not in ("text", "sys"):
            continue
        sender_id = getattr(m, "sender_id", "") or ""
        try:
            delay_ms = int(getattr(m, "delay_ms", 0) or 0)
        except (TypeError, ValueError):
            delay_ms = 0
        start_ms = cumulative
        end_ms = start_ms + max(0, delay_ms)
        text = (getattr(m, "text", None) or "").strip()
        segments.append({
            "speaker_id": str(sender_id),
            "speaker": name_by_id.get(str(sender_id)),
            "text": text,
            "start_ms": start_ms,
            "end_ms": end_ms,
        })
        cumulative = end_ms

    return {"segments": segments}


# ---------- 合成核心 ----------

def _resolve_segment_speaker(speaker_id: str, role_map: dict[str, str]) -> str:
    """speaker_id → 内置 speaker 名。优先级:per-task role_map > 全局默认 > 兜底 Ryan。"""
    if speaker_id in role_map and role_map[speaker_id]:
        return role_map[speaker_id]
    defaults = _voice_config.get("default_speakers") or {}
    if speaker_id in defaults and defaults[speaker_id]:
        return defaults[speaker_id]
    # 文档兜底:未知角色统一给 Ryan
    return "Ryan"


def _resolve_segment_instruct(speaker_id: str, instructs: dict[str, str]) -> str | None:
    """speaker_id → TTS instruct 文案;没有时返回 None(模型会用默认语气)。"""
    if speaker_id in instructs and instructs[speaker_id]:
        return instructs[speaker_id]
    defaults = _voice_config.get("default_instructs") or {}
    return defaults.get(speaker_id)


def _generate_silence(duration_ms: int, sr: int) -> Any:
    """生成指定毫秒数的静音 float32 数组。"""
    import numpy as np  # type: ignore

    n = max(0, int(round(sr * max(0, duration_ms) / 1000.0)))
    return np.zeros(n, dtype=np.float32)


def _tts_metadata_path(wav_path: Path) -> Path:
    """outputs/{job_id}.meta.json 路径 —— 与 wav 同目录,仅合成完成后存在。"""
    return wav_path.with_name(f"{wav_path.stem}.meta.json")


async def _synthesize_one_segment(
    model: Any,
    *,
    text: str,
    speaker: str,
    instruct: str | None,
    language: str,
    target_sr: int,
) -> Any:
    """单段推理。model_lock 由调用方(synthesize 主循环)持有,这里只做参数拼装 + wait_for。

    model.generate_custom_voice 是 blocking(torch)调用,丢进 to_thread 不阻塞事件循环;
    但因为锁在外层,其他 worker 即便被调度到这里也会先 await _model_lock,排队。
    """
    import numpy as np  # type: ignore

    kwargs: dict[str, Any] = {
        "text": text,
        "language": language,
        "speaker": speaker,
    }
    if instruct:
        kwargs["instruct"] = instruct

    def _do() -> tuple[Any, int]:
        wavs, gen_sr = model.generate_custom_voice(**kwargs)
        return wavs, int(gen_sr)

    wavs, gen_sr = await asyncio.wait_for(
        asyncio.to_thread(_do),
        timeout=TTS_INFERENCE_TIMEOUT_S,
    )
    wav = np.asarray(wavs[0], dtype=np.float32)
    if gen_sr != target_sr:
        from scipy import signal  # type: ignore

        num = max(1, int(round(len(wav) * target_sr / gen_sr)))
        wav = signal.resample(wav, num).astype(np.float32)
    return wav


async def synthesize(
    job_id: str,
    user_id: str,
    session_id: str,
    config: dict[str, Any],
    progress_cb: ProgressCallback,
) -> Path:
    """合成入口。签名与 recorder.render_video 对齐(5 参数),返回 wav 路径。

    config 字段(由 POST /api/tts 落库 jobs.config_json):
      asr_file_id: str              required
      role_map: dict[sid→speaker]  optional,空走全局默认
      instructs: dict[sid→instruct] optional,空走全局默认
      model_path: str              optional,覆盖 TTS_MODEL_PATH
      target_sr: int               optional,覆盖 TTS_TARGET_SR
      language: str                optional,覆盖 TTS_LANGUAGE

    副作用:写 outputs/{job_id}.wav 与 outputs/{job_id}.meta.json;
          meta.json 在 done 路径由 queue._process_job 读取后删除。
    """
    await progress_cb(1)

    # 1. 读 ASR JSON
    asr_file_id = config.get("asr_file_id")
    if not asr_file_id:
        raise RuntimeError("config.asr_file_id is required")

    # 延迟导入避免循环(此模块会被 queue 导入,queue 又会被这里用到)
    from app import db
    from app.storage import upload_path

    file_row = db.get_file(asr_file_id)
    if file_row is None:
        raise RuntimeError(f"ASR file not found: {asr_file_id}")
    if file_row["user_id"] != user_id or file_row["session_id"] != session_id:
        raise RuntimeError("ASR file does not belong to this user/session")
    if file_row.get("kind") != "asr":
        raise RuntimeError(f"file kind must be 'asr', got {file_row.get('kind')!r}")

    asr_path = upload_path(user_id, session_id, asr_file_id, file_row["ext"])
    if not asr_path.is_file():
        raise RuntimeError(f"ASR JSON missing on disk: {asr_path}")

    try:
        asr_data = json.loads(asr_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"failed to parse ASR JSON: {exc}") from exc
    parsed = parse_asr_json(asr_data)
    segments: list[dict[str, Any]] = parsed["segments"]

    # 2. 解析 per-task override
    role_map: dict[str, str] = dict(config.get("role_map") or {})
    instructs: dict[str, str] = dict(config.get("instructs") or {})
    target_sr = int(config.get("target_sr") or TTS_TARGET_SR)
    language = str(config.get("language") or TTS_LANGUAGE)
    override_model_path = config.get("model_path") or None

    if target_sr <= 0:
        raise RuntimeError(f"target_sr must be positive, got {target_sr}")

    # 3. 加载模型(走 _model_lock;耗时,首调用可能 1-2 分钟)
    await progress_cb(3)
    model = await _get_model(override_model_path)

    # 4. 准备产物路径
    wav_path = output_path(user_id, session_id, job_id, EXT_AUDIO_WAV)
    wav_path.parent.mkdir(parents=True, exist_ok=True)

    # 5. 逐段合成;失败段回退静音 + 写 metadata
    failed_segments: list[dict[str, Any]] = []
    audio_parts: list[Any] = []
    n_total = len(segments)

    for i, seg in enumerate(segments):
        speaker_id = str(seg.get("speaker_id", ""))
        text = (seg.get("text") or "").strip()
        start_ms = int(seg.get("start_ms", 0))
        end_ms = int(seg.get("end_ms", 0))
        duration_ms = max(0, end_ms - start_ms)

        if speaker_id == "__system__" or not text:
            audio_parts.append(_generate_silence(duration_ms, target_sr))
            logger.info(
                "[%d/%d] [system] silence %dms", i + 1, n_total, duration_ms,
            )
        else:
            speaker = _resolve_segment_speaker(speaker_id, role_map)
            instruct = _resolve_segment_instruct(speaker_id, instructs)
            logger.info(
                "[%d/%d] [%s(%s)] %s",
                i + 1, n_total, speaker_id, speaker, text[:40],
            )
            try:
                wav = await _synthesize_one_segment(
                    model,
                    text=text,
                    speaker=speaker,
                    instruct=instruct,
                    language=language,
                    target_sr=target_sr,
                )
                audio_parts.append(wav)
            except Exception as exc:  # noqa: BLE001 — 单段失败只回退 + 记 metadata
                logger.warning(
                    "[%d/%d] [%s(%s)] synthesis failed: %s; filling with silence",
                    i + 1, n_total, speaker_id, speaker, exc,
                )
                failed_segments.append({
                    "idx": i,
                    "speaker_id": speaker_id,
                    "speaker": speaker,
                    "text": text[:80],
                    "reason": str(exc),
                })
                audio_parts.append(_generate_silence(duration_ms, target_sr))

        # 进度:1-3 初始化,4-94 segment 循环,95-99 收尾
        if n_total > 0:
            seg_pct = 4 + int((i + 1) / n_total * 90)
            await progress_cb(seg_pct)

    # 6. 拼接 + 落盘 wav
    import numpy as np  # type: ignore
    import soundfile as sf  # type: ignore

    await progress_cb(96)
    if audio_parts:
        final = np.concatenate(audio_parts)
    else:
        final = np.zeros(0, dtype=np.float32)
    sf.write(str(wav_path), final, target_sr)
    duration_s = len(final) / target_sr if target_sr else 0
    await progress_cb(99)

    # 7. 写 meta.json 给 _process_job 收尾(空失败列表也写,前端可据此确认 0 失败)
    meta_path = _tts_metadata_path(wav_path)
    meta_path.write_text(
        json.dumps({"failed_segments": failed_segments}, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info(
        "TTS job=%s done: %d segments, %d failed, %.1fs wav, %d bytes",
        job_id, n_total, len(failed_segments), duration_s, wav_path.stat().st_size,
    )
    return wav_path
