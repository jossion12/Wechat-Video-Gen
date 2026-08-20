"""DSL 数据模型 — 视频生成的单一事实源。

VideoDSL 是顶层 DSL,scene 字段承载具体场景配置。
当前仅支持 chat 场景;未来可扩展 slide / subtitle 等场景。
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import (
    FIRST_MESSAGE_MIN_DELAY_MS,
    MAX_DURATION_MS,
    MAX_MESSAGES,
    MIN_PARTICIPANTS,
    Message,
    Participant,
    StatusBar,
    WatermarkConfig,
)

SCHEMA_VERSION = "1.0"


def auto_duration(messages: list[Message], first_delay_ms: int = 500) -> int:
    """自动算总时长:第一条消息显示时间 + 各消息 delay 之和 + 结尾 buffer。"""
    base = first_delay_ms + sum(m.delay_ms for m in messages)
    return base + 1500


class ChatScene(BaseModel):
    """聊天场景配置。"""

    mode: Literal["single", "group"] = "group"
    title: str = "群聊"
    subtitle: str | None = None  # 单聊时显示在标题下方,如企业备注
    background: str = "#ededed"
    background_image_url: str | None = None  # 整页背景图;有值时优先于 background 颜色
    duration_ms: int | None = None  # None = 自动算
    opacity: float = 1.0  # 0-1,整个内容透明度,方便叠加到其他视频
    status_bar: StatusBar = Field(default_factory=StatusBar)
    member_count: int | None = None  # 群聊人数,如 221
    muted: bool = False  # 群聊免打扰铃铛
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

    @field_validator("opacity")
    @classmethod
    def opacity_range(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError("opacity must be between 0 and 1")
        return v

    @model_validator(mode="after")
    def check_references(self) -> "ChatScene":
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
        return self


class VideoDSL(BaseModel):
    """视频生成顶层 DSL。

    kind 标识场景类型,template 标识同一场景下的视觉风格,
    scene 承载具体场景数据。
    """

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    kind: Literal["chat"] = "chat"
    template: Literal["wechat"] = "wechat"
    scene: ChatScene


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
