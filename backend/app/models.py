"""Pydantic 数据模型 — 见 docs/02-data-model.md。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

if TYPE_CHECKING:
    from app.dsl import VideoDSL

SYSTEM_SENDER_ID = "__system__"

MAX_PARTICIPANT_NAME = 16
MAX_PARTICIPANT_LABEL = 24
MAX_MESSAGE_TEXT = 500
MAX_MESSAGES = 30
MIN_PARTICIPANTS = 2
FIRST_MESSAGE_MIN_DELAY_MS = 500
MAX_DURATION_MS = 300_000  # 5 分钟上限,防止误配超长任务
MAX_STATUS_BAR_APP_ICONS = 3


class StatusBar(BaseModel):
    """顶部状态栏。"""

    time: str = "12:34"
    battery_level: int = 100
    network_speed: str | None = None  # e.g. "3.5 K/s", "300 B/s"
    signal_type: str | None = None  # e.g. "5A", "5G", "4G"
    signal_type_secondary: str | None = None  # e.g. "5G", used when dual_sim is true
    dual_sim: bool = False
    show_wifi: bool = True
    show_signal: bool = True
    show_bluetooth: bool = False
    show_alarm: bool = False
    show_nfc: bool = False
    app_icons: list[str] = Field(default_factory=list)

    @field_validator("time")
    @classmethod
    def time_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("status_bar.time must not be empty")
        return v

    @field_validator("battery_level")
    @classmethod
    def battery_range(cls, v: int) -> int:
        if v < 0 or v > 100:
            raise ValueError("status_bar.battery_level must be 0-100")
        return v

    @field_validator("app_icons")
    @classmethod
    def app_icons_limit(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_STATUS_BAR_APP_ICONS:
            raise ValueError(
                f"status_bar.app_icons must be <= {MAX_STATUS_BAR_APP_ICONS}"
            )
        return v


class Participant(BaseModel):
    """聊天参与者。"""

    id: str
    name: str = Field(max_length=MAX_PARTICIPANT_NAME)
    avatar_url: str | None = None
    label: str | None = None  # 单聊副标题 / 群聊企业标签

    @field_validator("id")
    @classmethod
    def id_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("participant id must not be empty")
        return v


class Message(BaseModel):
    """一条聊天消息(text / image / sys / timestamp / video / emoji)。"""

    sender_id: str
    kind: Literal["text", "image", "sys", "timestamp", "video", "emoji"]
    text: str | None = None
    image_url: str | None = None
    video_url: str | None = None
    cover_url: str | None = None
    duration: str | None = None  # 视频/语音时长,如 "0:10"
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
        if self.kind == "video":
            if not self.video_url:
                raise ValueError("video message must have video_url")
            if not self.duration:
                raise ValueError("video message must have duration")
        if self.kind == "emoji" and not self.text:
            raise ValueError("emoji message must have non-empty text")
        if self.kind == "timestamp" and not self.text:
            raise ValueError("timestamp message must have non-empty text")
        if self.kind == "sys":
            if not self.text:
                raise ValueError("sys message must have non-empty text")
            if self.image_url:
                raise ValueError("sys message cannot have image_url")
        return self


class JobStatus(BaseModel):
    """API 返回的任务状态(不含 config)。"""

    id: str
    status: Literal["queued", "running", "done", "failed"]
    progress: int
    output_url: str | None
    error: str | None
    created_at: float
    finished_at: float | None
