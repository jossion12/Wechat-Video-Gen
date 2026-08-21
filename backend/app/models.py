"""Pydantic 数据模型 — 见 docs/02-data-model.md。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

if TYPE_CHECKING:
    from app.dsl import VideoDSL

SYSTEM_SENDER_ID = "__system__"

MAX_PARTICIPANT_NAME = 16
MAX_PARTICIPANT_PERSONA = 200
MAX_MESSAGE_TEXT = 500
MAX_MESSAGES = 100
MIN_PARTICIPANTS = 2
FIRST_MESSAGE_MIN_DELAY_MS = 500
MAX_DURATION_MS = 300_000  # 5 分钟上限,防止误配超长任务

# ---------- 合规相关常量 ----------

AI_GENERATION_NOTICE = "本内容由 AI 生成 · 仅供创意表达"
DISCLAIMER_CARD_TEXT = "本对话由 AI 生成，仅供创意表达"

ALLOWED_INTENTS = [
    "short_video_drama",      # 短视频剧情创作
    "story_visualization",    # 情感故事 / 小说可视化
    "teaching_simulation",    # 教学演示 / 情景模拟
    "meme_sticker",           # 表情包 / 梗图制作
]

INTENT_LABELS = {
    "short_video_drama": "短视频剧情创作",
    "story_visualization": "情感故事 / 小说可视化",
    "teaching_simulation": "教学演示 / 情景模拟",
    "meme_sticker": "表情包 / 梗图制作",
}

# 高敏感词:命中后渲染请求被拒绝
HIGH_RISK_WORDS = [
    "转账", "红包", "密码", "验证码", "银行卡", "汇款", "借款",
    "信用卡", "借记卡", "账户余额", "支付密码", "登录密码",
]

# 真实社交平台名称:命中后提示不要模仿真实平台
PLATFORM_NAMES = [
    "微信", "WeChat", "WhatsApp", "腾讯", "Tencent", "Meta", "Facebook",
    "Messenger", "Line", "Telegram", "钉钉", "飞书", "Slack",
]

# 角标样式(仅视觉,不可关闭)
AI_BADGE_STYLES = ["neon", "minimal", "retro"]

# 视觉风格模板
STYLE_THEMES = ["cyberpunk", "watercolor", "pixel", "comic", "noir"]
STYLE_THEME_LABELS = {
    "cyberpunk": "赛博朋克",
    "watercolor": "手绘",
    "pixel": "复古",
    "comic": "漫画",
    "noir": "黑白胶片",
}


class Participant(BaseModel):
    """聊天参与者(对话剧场中的角色)。"""

    id: str
    name: str = Field(max_length=MAX_PARTICIPANT_NAME)
    avatar_url: str | None = None
    persona: str | None = None  # 角色设定 / 性格标签(MVE 仅存储)

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
    align: Literal["left", "right"] | None = None  # 显式指定消息方向;None 时按旧规则推断
    reply_to: int | None = None  # 回复目标的 1-based 序号;None 表示普通消息

    @field_validator("reply_to")
    @classmethod
    def reply_to_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("reply_to must be >= 1")
        return v

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


# ---------- 多用户 / session 相关(新增) ----------

class WatermarkConfig(BaseModel):
    """AI 生成标识配置 —— 不可关闭,仅可切换角标视觉样式。"""

    text: str = AI_GENERATION_NOTICE
    badge_style: Literal["neon", "minimal", "retro"] = "neon"


class UserInfo(BaseModel):
    """当前用户信息。MVE 阶段保留 registered_at / paid_at 字段但不再用于去水印。"""

    id: str
    username: str
    created_at: float
    registered_at: float | None = None
    paid_at: float | None = None


class SessionInfo(BaseModel):
    """session 摘要信息。"""

    id: str
    user_id: str
    title: str | None
    created_at: float
    last_active_at: float
    file_count: int = 0
    job_count: int = 0


class SessionDetail(SessionInfo):
    """session 详情 = 摘要 + 文件列表 + 任务列表。"""

    files: list["FileInfo"] = Field(default_factory=list)
    jobs: list["JobSummary"] = Field(default_factory=list)


class CreateSessionRequest(BaseModel):
    """POST /api/sessions 请求体。"""

    title: str | None = None


class FileInfo(BaseModel):
    """素材文件元信息(avatar / image / background)。"""

    id: str
    session_id: str
    user_id: str
    kind: Literal["avatar", "image", "background"]
    ext: str
    size: int
    content_type: str | None
    created_at: float
    url: str  # 形如 /api/files/{file_id},可直接赋给 dsl.avatar_url 等


class JobSummary(BaseModel):
    """session 详情里的任务列表项(不含 config,体积小)。"""

    id: str
    session_id: str
    user_id: str
    status: Literal["queued", "running", "done", "failed"]
    progress: int
    output_url: str | None
    error: str | None
    created_at: float
    finished_at: float | None


SessionDetail.model_rebuild()
