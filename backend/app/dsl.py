"""DSL 数据模型 — 视频生成的单一事实源。

VideoDSL 是顶层 DSL,scene 字段承载具体场景配置。
当前仅支持 chat 场景;未来可扩展 slide / subtitle 等场景。
"""

from __future__ import annotations

import re
import time
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import (
    AI_BADGE_STYLES,
    ALLOWED_INTENTS,
    FIRST_MESSAGE_MIN_DELAY_MS,
    HIGH_RISK_WORDS,
    INTRO_EFFECTS,
    MAX_DURATION_MS,
    MAX_MESSAGES,
    MIN_PARTICIPANTS,
    PLATFORM_NAMES,
    STYLE_THEMES,
    Message,
    Participant,
    WatermarkConfig,
)

SCHEMA_VERSION = "1.0"


def auto_duration(messages: list[Message], first_delay_ms: int = 500) -> int:
    """自动算总时长:第一条消息显示时间 + 各消息 delay 之和 + 结尾 buffer。"""
    base = first_delay_ms + sum(m.delay_ms for m in messages)
    return base + 1500


def _contains_platform_name(text: str, name: str) -> bool:
    """检测文本中是否包含真实社交平台名。

    中文平台名按子串匹配;英文平台名按单词边界匹配,
    避免 "Meta" 误杀 "Metal" 等技术词汇。
    """
    if any("\u4e00" <= ch <= "\u9fff" for ch in name):
        return name in text
    return re.search(rf"\b{re.escape(name)}\b", text) is not None


class ChatScene(BaseModel):
    """对话剧场场景配置。"""

    mode: Literal["single", "group"] = "group"
    title: str = "对话剧场"
    background: str = "#ffffff"
    background_image_url: str | None = None  # 整页背景图;有值时叠加于背景色之上
    duration_ms: int | None = None  # None = 自动算
    opacity: float = 1.0  # 0-1,整个内容透明度,方便叠加到其他视频
    intro_effect: Literal["none", "scanline", "typewriter"] = "none"
    style_theme: Literal["cyberpunk", "watercolor", "pixel", "comic", "noir", "ink"] = "comic"
    intent: str = ""
    intent_acknowledged: bool = False
    participants: list[Participant] = Field(min_length=MIN_PARTICIPANTS)
    messages: list[Message] = Field(min_length=1, max_length=MAX_MESSAGES)
    watermark: WatermarkConfig = Field(default_factory=WatermarkConfig)

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be empty")
        if len(v) > 40:
            raise ValueError("title must be <= 40 chars")
        return v

    @field_validator("background")
    @classmethod
    def background_hex(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("#") or len(v) not in (4, 7):
            raise ValueError("background must be a hex color like #0a0a12")
        return v

    @field_validator("duration_ms")
    @classmethod
    def duration_range(cls, v: int | None) -> int | None:
        if v is not None:
            if v <= 0:
                raise ValueError("duration_ms must be a positive integer")
            if v > MAX_DURATION_MS:
                raise ValueError(f"duration_ms must be <= {MAX_DURATION_MS}")
        return v

    @field_validator("opacity")
    @classmethod
    def opacity_range(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError("opacity must be between 0 and 1")
        return v

    @field_validator("intent")
    @classmethod
    def intent_allowed(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must select a creation intent")
        if v not in ALLOWED_INTENTS:
            raise ValueError(f"intent must be one of {ALLOWED_INTENTS}")
        return v

    @model_validator(mode="after")
    def check_references(self) -> "ChatScene":
        if not self.intent_acknowledged:
            raise ValueError("must acknowledge the compliance agreement")
        if self.mode == "single" and len(self.participants) != 2:
            raise ValueError("single mode requires exactly 2 participants")
        ids = {p.id for p in self.participants}
        if len(ids) != len(self.participants):
            raise ValueError("participant ids must be unique")
        for m in self.messages:
            if m.kind not in {"sys", "timestamp"} and m.sender_id not in ids:
                raise ValueError(
                    f"sender_id {m.sender_id!r} does not match any participant id"
                )
        if self.messages and self.messages[0].delay_ms < FIRST_MESSAGE_MIN_DELAY_MS:
            raise ValueError(
                "first message delay_ms must be >= "
                f"{FIRST_MESSAGE_MIN_DELAY_MS} (leave time for the timestamp)"
            )
        # 敏感词与真实平台名检测
        for m in self.messages:
            text = (m.text or "")
            for word in HIGH_RISK_WORDS:
                if word in text:
                    raise ValueError(
                        f"high-risk content detected: '{word}'. "
                        "Please ensure it is used for legitimate creative purposes only."
                    )
            for name in PLATFORM_NAMES:
                if _contains_platform_name(text, name):
                    raise ValueError(
                        f"real platform name '{name}' detected. "
                        "Please do not imitate real social platforms."
                    )
        # 回复引用校验:只能引用之前且非 sys/timestamp 的消息
        for idx, m in enumerate(self.messages, start=1):
            if m.reply_to is None:
                continue
            if not isinstance(m.reply_to, int) or m.reply_to < 1 or m.reply_to >= idx:
                raise ValueError(
                    f"message {idx}: reply_to must be an integer >= 1 and "
                    "less than the current message index"
                )
            if m.reply_to > len(self.messages):
                raise ValueError(
                    f"message {idx}: reply_to points to a non-existent message"
                )
            target = self.messages[m.reply_to - 1]
            if target.kind in {"sys", "timestamp"}:
                raise ValueError(
                    f"message {idx}: cannot reply to a {target.kind} message"
                )
        return self


class VideoDSL(BaseModel):
    """视频生成顶层 DSL。

    kind 标识场景类型,template 标识同一场景下的视觉风格,
    scene 承载具体场景数据。
    """

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    kind: Literal["chat"] = "chat"
    template: Literal["cyberpunk", "watercolor", "pixel", "comic", "noir", "ink"] = "cyberpunk"
    scene: ChatScene

    @model_validator(mode="after")
    def sync_template_and_style_theme(self) -> "VideoDSL":
        """保持 template 与 scene.style_theme 一致,以 template 为准。"""
        if self.scene.style_theme != self.template:
            self.scene.style_theme = self.template
        return self


class Job(BaseModel):
    """录制任务(后端内部状态)。"""

    id: str
    status: Literal["queued", "running", "done", "failed"] = "queued"
    progress: int = 0
    config: VideoDSL
    output_url: str | None = None
    error: str | None = None
    created_at: float = Field(default_factory=time.time)
    finished_at: float | None = None
