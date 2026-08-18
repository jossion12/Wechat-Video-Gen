"""Pydantic 数据模型 — 见 docs/02-data-model.md。"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SYSTEM_SENDER_ID = "__system__"

MAX_PARTICIPANT_NAME = 16
MAX_MESSAGE_TEXT = 500
MAX_MESSAGES = 30
MIN_PARTICIPANTS = 2
FIRST_MESSAGE_MIN_DELAY_MS = 500
MAX_DURATION_MS = 300_000  # 5 分钟上限,防止误配超长任务


class Participant(BaseModel):
    """聊天参与者。"""

    id: str
    name: str = Field(max_length=MAX_PARTICIPANT_NAME)
    avatar_url: str | None = None

    @field_validator("id")
    @classmethod
    def id_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("participant id must not be empty")
        return v


class Message(BaseModel):
    """一条聊天消息(text / image / sys)。"""

    sender_id: str
    kind: Literal["text", "image", "sys"]
    text: str | None = None
    image_url: str | None = None
    delay_ms: int = 1500

    @field_validator("text")
    @classmethod
    def normalize_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None  # 空白串视为空

    @field_validator("delay_ms")
    @classmethod
    def delay_positive(cls, v: int) -> int:
        if v < 100:
            raise ValueError("delay_ms must be >= 100")
        if v > 60_000:
            raise ValueError("delay_ms must be <= 60000")
        return v

    @field_validator("text")
    @classmethod
    def text_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) > MAX_MESSAGE_TEXT:
            raise ValueError(f"text must be <= {MAX_MESSAGE_TEXT} chars")
        return v

    @model_validator(mode="after")
    def check_kind_fields(self) -> "Message":
        if self.kind == "text" and not self.text:
            raise ValueError("text message must have non-empty text")
        if self.kind == "image" and not self.image_url:
            raise ValueError("image message must have image_url")
        if self.kind == "sys":
            if not self.text:
                raise ValueError("sys message must have non-empty text")
            if self.image_url:
                raise ValueError("sys message cannot have image_url")
        return self


class ChatConfig(BaseModel):
    """一次完整配置。"""

    mode: Literal["single", "group"] = "group"
    title: str = "群聊"
    background: str = "#ededed"
    duration_ms: int | None = None  # None = 自动算
    participants: list[Participant] = Field(min_length=MIN_PARTICIPANTS)
    messages: list[Message] = Field(min_length=1, max_length=MAX_MESSAGES)

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
            raise ValueError("background must be a hex color like #ededed")
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

    @model_validator(mode="after")
    def check_references(self) -> "ChatConfig":
        ids = {p.id for p in self.participants}
        if len(ids) != len(self.participants):
            raise ValueError("participant ids must be unique")
        for m in self.messages:
            if m.kind != "sys" and m.sender_id not in ids:
                raise ValueError(
                    f"sender_id {m.sender_id!r} does not match any participant id"
                )
        if self.messages and self.messages[0].delay_ms < FIRST_MESSAGE_MIN_DELAY_MS:
            raise ValueError(
                "first message delay_ms must be >= "
                f"{FIRST_MESSAGE_MIN_DELAY_MS} (leave time for the timestamp)"
            )
        # 单聊不限制参与者数量(至少 2 个,见 participants min_length);
        # 方向规则见 renderer._is_self:participants[0] 视为"我",其余走左侧。
        return self


class Job(BaseModel):
    """录制任务(后端内部状态)。"""

    id: str
    status: Literal["queued", "running", "done", "failed"] = "queued"
    progress: int = 0
    config: ChatConfig
    output_url: str | None = None
    error: str | None = None
    created_at: float = Field(default_factory=time.time)
    finished_at: float | None = None


class JobStatus(BaseModel):
    """API 返回的任务状态(不含 config)。"""

    id: str
    status: Literal["queued", "running", "done", "failed"]
    progress: int
    output_url: str | None
    error: str | None
    created_at: float
    finished_at: float | None


def auto_duration(messages: list[Message], first_delay_ms: int = 1200) -> int:
    """自动算总时长:第一条消息的时间戳间隔 + 各消息 delay 之和 + 前后 buffer。"""
    base = first_delay_ms + sum(m.delay_ms for m in messages)
    return base + 1500
