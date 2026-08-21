"""AI 辅助对话生成服务。

通过 OpenAI 兼容的 Chat Completion API 生成 / 续写对话 DSL。
配置项全部来自环境变量,不硬编码具体模型或供应商。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.dsl import ChatScene, VideoDSL
from app.models import (
    AI_GENERATION_NOTICE,
    ALLOWED_INTENTS,
    Message,
    Participant,
    STYLE_THEMES,
    WatermarkConfig,
)

logger = logging.getLogger("ai_service")

# ---------- 配置 ----------

AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "4096"))
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.8"))
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "60"))
AI_DAILY_LIMIT = int(os.getenv("AI_DAILY_LIMIT", "50"))

# 简单内存级日配额;重启进程会清空,适合 MVP。生产应换 Redis / DB。
_quota: dict[str, tuple[int, float]] = defaultdict(lambda: (0, time.time()))


# ---------- 异常 ----------


class AIServiceError(Exception):
    """AI 服务调用失败的领域异常。"""

    def __init__(self, message: str, code: str = "ai_error"):
        super().__init__(message)
        self.code = code


# ---------- 配额 ----------


def _check_quota(user_id: str) -> int:
    """返回今日剩余调用次数;超限抛 AIServiceError。"""
    if AI_DAILY_LIMIT <= 0:
        return -1
    count, reset_at = _quota[user_id]
    now = time.time()
    # 按自然日重置
    if now - reset_at >= 86400:
        count = 0
        reset_at = now
    remaining = AI_DAILY_LIMIT - count
    if remaining <= 0:
        raise AIServiceError(
            f"本日 AI 生成额度已用完（每日 {AI_DAILY_LIMIT} 次）", code="quota_exceeded"
        )
    return remaining


def _consume_quota(user_id: str) -> None:
    count, reset_at = _quota[user_id]
    now = time.time()
    if now - reset_at >= 86400:
        count = 0
        reset_at = now
    _quota[user_id] = (count + 1, reset_at)


# ---------- LLM 客户端 ----------


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    usage: dict[str, int] | None


def _build_client() -> httpx.AsyncClient:
    if not AI_API_KEY:
        raise AIServiceError(
            "AI_API_KEY not configured; AI generation is unavailable", code="not_configured"
        )
    return httpx.AsyncClient(
        base_url=AI_BASE_URL,
        headers={"Authorization": f"Bearer {AI_API_KEY}"},
        timeout=httpx.Timeout(AI_TIMEOUT_SECONDS),
    )


async def _chat_completion(
    messages: list[dict[str, str]],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> LLMResponse:
    async with _build_client() as client:
        payload: dict[str, Any] = {
            "model": AI_MODEL,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        try:
            resp = await client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise AIServiceError(
                f"AI 接口调用超时（{AI_TIMEOUT_SECONDS}s）。如果部署在 Docker 内且代理在宿主机运行，"
                "请把 AI_BASE_URL 从 localhost 改为 host.docker.internal 或宿主机 IP。",
                code="timeout",
            ) from exc
        except httpx.ConnectError as exc:
            raise AIServiceError(
                f"无法连接到 AI 接口 {AI_BASE_URL}。常见原因：\n"
                "1. Docker 容器内 localhost 指向容器自身，应改为 host.docker.internal（Docker Desktop）或宿主机 IP；\n"
                "2. AI 代理服务未启动；\n"
                "3. 防火墙/网络策略阻止了容器出站访问。",
                code="connect_error",
            ) from exc
        except httpx.HTTPError as exc:
            raise AIServiceError(f"AI 接口请求失败: {exc}", code="upstream_error") from exc

        if resp.status_code != 200:
            text = resp.text[:500]
            raise AIServiceError(
                f"AI 接口返回错误（HTTP {resp.status_code}）: {text}",
                code="upstream_error",
            )

        data = resp.json()
        choice = data.get("choices", [{}])[0]
        content = (choice.get("message", {}) or {}).get("content", "")
        if not content:
            raise AIServiceError("AI 返回空内容", code="empty_response")
        return LLMResponse(
            content=content,
            model=data.get("model", AI_MODEL),
            usage=data.get("usage"),
        )


# ---------- Prompt 与 JSON 抽取 ----------


def _extract_json_block(text: str) -> str:
    """从 LLM 输出里抽取 JSON 代码块或首个 JSON 对象。"""
    # 优先 ```json ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return match.group(1)
    # 再找裸露的 { ... }
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        return match.group(1)
    raise AIServiceError("无法从 AI 输出中解析 JSON", code="parse_error")


def _dsl_schema_prompt() -> str:
    """返回 VideoDSL scene 的 JSON 结构说明,供 LLM 遵循。"""
    return """
你必须返回一个合法 JSON 对象,结构如下:
{
  "title": "对话标题(不超过40字)",
  "participants": [
    { "id": "p1", "name": "角色名(不超过16字)", "persona": "角色设定/性格标签(可选,不超过200字)" },
    ...
  ],
  "messages": [
    {
      "sender_id": "p1",
      "kind": "text",
      "text": "消息文本(不超过500字)",
      "delay_ms": 1500
    },
    ...
  ]
}

字段规则:
- participants 至少 2 人,每人 id 唯一,建议用 p1/p2/p3...
- messages 至少 1 条,最多 20 条。
- kind 仅允许: text(文字) / sys(系统消息,幕间字幕) / timestamp(时间戳,如"星期五 18:27")。
  不要生成 image、video、emoji 类消息,因为前端编辑器暂不支持直接修改这些类型。
- sys/timestamp 消息的 sender_id 请用 "__system__"。
- delay_ms: 每条消息显示后到下一条的间隔,单位毫秒,范围 500-6000,默认 1500。
- 第一条消息的 delay_ms 必须 >= 500。
- 可适当使用 1-2 条 reply_to: N,表示回复第 N 条消息(1-based)。

内容合规:
- 禁止出现转账、红包、密码、验证码、银行卡、汇款、借款、信用卡、借记卡、账户余额、支付密码、登录密码等高风险词。
- 禁止出现微信、WeChat、WhatsApp、腾讯、Tencent、Meta、Facebook、Messenger、Line、Telegram、钉钉、飞书、Slack 等真实社交平台或公司名称。
- 这是原创风格的对话剧场,不要模仿任何真实社交应用界面。
"""


def _system_prompt_for_generate() -> str:
    return (
        "你是对话剧场 / Dialogue Theater 的 AI 编剧。"
        "你根据用户提供的剧情概要,创作一段适合生成短视频的对话。"
        "对话应自然、有戏剧性、适合短视频节奏,不要冗长。\n"
        + _dsl_schema_prompt()
    )


def _system_prompt_for_continue() -> str:
    return (
        "你是对话剧场 / Dialogue Theater 的 AI 编剧。"
        "你根据用户已写好的对话上下文,续写接下来的 3 条候选消息。"
        "每条候选要符合剧情发展,风格与已有对话保持一致。"
        "候选消息 kind 只允许 text / sys / timestamp。\n"
        + _dsl_schema_prompt().replace(
            '"messages": [\n    {\n      "sender_id": "p1",\n      "kind": "text",',
            '"candidates": [\n    {\n      "sender_id": "p1",\n      "kind": "text",',
        )
        + "\n返回 JSON 顶层键为: candidates(数组)。"
    )


# ---------- 生成/续写核心 ----------


def _make_default_scene(
    mode: Literal["single", "group"],
    style_theme: str,
    intent: str,
    title: str,
) -> ChatScene:
    """用 AI 生成结果补齐成一个完整可渲染的 ChatScene。

    ChatScene 要求至少 2 名参与者和 1 条消息,因此先填入占位数据,
    再由 _merge_generated 覆盖。
    """
    # 与前端 THEME_DEFAULT_BACKGROUND 保持同步
    bg_map = {
        "cyberpunk": "#0a0a12",
        "watercolor": "#f7f4ed",
        "pixel": "#051005",
        "comic": "#ffffff",
    }
    placeholders = [
        Participant(id="p1", name="角色1"),
        Participant(id="p2", name="角色2"),
    ]
    placeholder_msg = Message(
        sender_id="p1",
        kind="text",
        text="placeholder",
        delay_ms=1500,
    )
    return ChatScene(
        mode=mode,
        title=title,
        background=bg_map.get(style_theme, "#ffffff"),
        style_theme=style_theme,  # type: ignore[arg-type]
        intent=intent,
        intent_acknowledged=True,
        participants=placeholders,
        messages=[placeholder_msg],
        watermark=WatermarkConfig(text=AI_GENERATION_NOTICE),
    )


def _merge_generated(
    scene: ChatScene,
    participants_data: list[dict],
    messages_data: list[dict],
) -> VideoDSL:
    """把 LLM 生成的 participants/messages 合并成合法 VideoDSL,并用 Pydantic 校验。"""
    participants = [Participant.model_validate(p) for p in participants_data]
    messages: list[Message] = []
    for idx, m in enumerate(messages_data, start=1):
        # 清理多余字段,保证 kind 合法
        kind = m.get("kind", "text")
        if kind not in {"text", "image", "sys", "timestamp", "video", "emoji"}:
            kind = "text"
        msg = Message(
            sender_id=m.get("sender_id", ""),
            kind=kind,  # type: ignore[arg-type]
            text=m.get("text") or None,
            image_url=m.get("image_url") or None,
            video_url=m.get("video_url") or None,
            cover_url=m.get("cover_url") or None,
            duration=m.get("duration") or None,
            delay_ms=int(m.get("delay_ms", 1500)),
            align=m.get("align") if m.get("align") in ("left", "right") else None,  # type: ignore[arg-type]
            reply_to=int(m["reply_to"]) if m.get("reply_to") is not None else None,
        )
        # 简单修正越界 reply_to
        if msg.reply_to is not None and (msg.reply_to < 1 or msg.reply_to >= idx):
            msg = msg.model_copy(update={"reply_to": None})
        messages.append(msg)

    merged = scene.model_copy(update={
        "participants": participants,
        "messages": messages,
    })
    dsl = VideoDSL(template=scene.style_theme, scene=merged)
    return dsl


async def generate_dialogue(
    user_id: str,
    synopsis: str,
    mode: Literal["single", "group"] = "group",
    style_theme: str = "comic",
    intent: str = "short_video_drama",
    num_messages: int = 8,
) -> VideoDSL:
    """根据剧情概要生成完整对话 DSL。"""
    _check_quota(user_id)
    if style_theme not in STYLE_THEMES:
        style_theme = "comic"
    if intent not in ALLOWED_INTENTS:
        intent = "short_video_drama"

    user_prompt = (
        f"创作意图: {intent}\n"
        f"对话模式: {mode}\n"
        f"视觉风格: {style_theme}\n"
        f"期望消息数: {max(2, min(num_messages, 20))} 条\n"
        f"剧情概要:\n{synopsis}\n\n"
        "请直接返回 JSON,不要有多余解释。"
    )

    llm = await _chat_completion(
        [
            {"role": "system", "content": _system_prompt_for_generate()},
            {"role": "user", "content": user_prompt},
        ],
        temperature=AI_TEMPERATURE,
        max_tokens=AI_MAX_TOKENS,
    )

    try:
        raw = json.loads(_extract_json_block(llm.content))
    except json.JSONDecodeError as exc:
        raise AIServiceError(f"AI 返回的不是合法 JSON: {exc}", code="parse_error") from exc

    title = str(raw.get("title", "AI 生成对话")).strip() or "AI 生成对话"
    scene = _make_default_scene(mode, style_theme, intent, title)
    try:
        dsl = _merge_generated(scene, raw.get("participants", []), raw.get("messages", []))
    except Exception as exc:
        raise AIServiceError(f"AI 生成内容校验失败: {exc}", code="validation_error") from exc

    _consume_quota(user_id)
    logger.info("generate_dialogue user=%s model=%s messages=%d", user_id, llm.model, len(dsl.scene.messages))
    return dsl


async def continue_dialogue(
    user_id: str,
    current_scene: ChatScene,
    num_candidates: int = 3,
) -> list[Message]:
    """根据已有对话续写若干候选消息。"""
    _check_quota(user_id)
    if not current_scene.messages:
        raise AIServiceError("当前对话为空，无法续写", code="empty_context")

    context_json = {
        "mode": current_scene.mode,
        "style_theme": current_scene.style_theme,
        "intent": current_scene.intent,
        "participants": [
            {"id": p.id, "name": p.name, "persona": p.persona}
            for p in current_scene.participants
        ],
        "messages": [
            {
                "sender_id": m.sender_id,
                "kind": m.kind,
                "text": m.text,
                "delay_ms": m.delay_ms,
            }
            for m in current_scene.messages[-20:]  # 只给最近 20 条作为上下文
        ],
    }

    user_prompt = (
        f"请续写 {num_candidates} 条候选消息,保持剧情连贯。\n"
        "当前上下文:\n"
        f"{json.dumps(context_json, ensure_ascii=False, indent=2)}\n\n"
        "请直接返回 JSON: {\"candidates\": [...]}"
    )

    llm = await _chat_completion(
        [
            {"role": "system", "content": _system_prompt_for_continue()},
            {"role": "user", "content": user_prompt},
        ],
        temperature=AI_TEMPERATURE,
        max_tokens=AI_MAX_TOKENS,
    )

    try:
        raw = json.loads(_extract_json_block(llm.content))
    except json.JSONDecodeError as exc:
        raise AIServiceError(f"AI 返回的不是合法 JSON: {exc}", code="parse_error") from exc

    candidates_data = raw.get("candidates", [])
    if not isinstance(candidates_data, list):
        raise AIServiceError("AI 返回的 candidates 不是数组", code="parse_error")

    candidates: list[Message] = []
    participant_ids = {p.id for p in current_scene.participants} | {"__system__"}
    for m in candidates_data[:num_candidates]:
        sender_id = m.get("sender_id", "")
        if sender_id not in participant_ids:
            sender_id = current_scene.participants[0].id if current_scene.participants else "p1"
        kind = m.get("kind", "text")
        if kind not in {"text", "image", "sys", "timestamp", "video", "emoji"}:
            kind = "text"
        try:
            msg = Message(
                sender_id=sender_id,
                kind=kind,  # type: ignore[arg-type]
                text=m.get("text") or None,
                image_url=m.get("image_url") or None,
                video_url=m.get("video_url") or None,
                cover_url=m.get("cover_url") or None,
                duration=m.get("duration") or None,
                delay_ms=int(m.get("delay_ms", 1500)),
                align=None,
                reply_to=None,
            )
            candidates.append(msg)
        except Exception as exc:
            logger.warning("continue_dialogue candidate validation skipped: %s", exc)
            continue

    if not candidates:
        raise AIServiceError("AI 没有生成任何可用候选", code="empty_response")

    _consume_quota(user_id)
    logger.info("continue_dialogue user=%s model=%s candidates=%d", user_id, llm.model, len(candidates))
    return candidates


# ---------- 连通性检查 ----------


async def check_ai_connection() -> dict[str, Any]:
    """测试 AI 接口连通性，不消耗配额。"""
    if not AI_API_KEY:
        return {
            "configured": False,
            "reachable": False,
            "base_url": AI_BASE_URL,
            "model": AI_MODEL,
            "reason": "AI_API_KEY not configured",
        }

    try:
        async with _build_client() as client:
            # 用最小请求测试连通性；很多供应商会返回 401/400，但网络是通的
            resp = await client.post(
                "/chat/completions",
                json={"model": AI_MODEL, "messages": []},
            )
            return {
                "configured": True,
                "reachable": True,
                "base_url": AI_BASE_URL,
                "model": AI_MODEL,
                "http_status": resp.status_code,
            }
    except AIServiceError as exc:
        return {
            "configured": True,
            "reachable": False,
            "base_url": AI_BASE_URL,
            "model": AI_MODEL,
            "code": exc.code,
            "reason": str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "configured": True,
            "reachable": False,
            "base_url": AI_BASE_URL,
            "model": AI_MODEL,
            "code": "unexpected",
            "reason": str(exc),
        }


# ---------- 配额查询 ----------


def get_quota_status(user_id: str) -> dict[str, int]:
    """返回用户今日 AI 调用配额状态。"""
    count, reset_at = _quota[user_id]
    now = time.time()
    if now - reset_at >= 86400:
        count = 0
    remaining = max(0, AI_DAILY_LIMIT - count) if AI_DAILY_LIMIT > 0 else -1
    return {
        "daily_limit": AI_DAILY_LIMIT,
        "used_today": count,
        "remaining_today": remaining,
    }
