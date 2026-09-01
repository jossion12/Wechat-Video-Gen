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
MAX_MESSAGES = 300
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

# 开头特效选项
INTRO_EFFECTS = ["none", "scanline", "typewriter"]

# 视觉风格模板
STYLE_THEMES = ["cyberpunk", "watercolor", "pixel", "comic", "noir", "ink", "green_screen"]
STYLE_THEME_LABELS = {
    "cyberpunk": "赛博朋克",
    "watercolor": "手绘",
    "pixel": "复古",
    "comic": "漫画",
    "noir": "黑白胶片",
    "ink": "水墨",
    "green_screen": "绿幕",
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
    # 时间码 JSON 产物(见 docs/03-api.md §3.x 时间码导出):
    # 仅 `status == "done"` 且磁盘上 timeline.json 真实存在时有值,形如
    # `/api/jobs/{id}/timeline`。前端据此展示「查看时间码」按钮。
    # TTS 任务没有 timeline.json → None。
    timeline_url: str | None = None
    # 任务类型:"render"(DSL→视频) / "tts"(ASR→wav)。前端按 kind 路由下载/播放 UI。
    # 旧 job 走 _ensure_columns 兼容迁移落 "render"。
    kind: str = "render"
    # 实际产物扩展名(由 db.jobs.output_ext 透出);前端在 done 事件里用来选播放器。
    output_ext: str | None = None
    # ⚠️ TTS 单段失败明细 —— Qwen3-TTS 多角色对话合成(DISABLED / DEPRECATED)⚠️
    # 见 docs/Qwen3-TTS_MultiSpeaker_Dialogue_Guide.md。当前版本下述字段不再使用,
    # 注释保留以便恢复 Qwen3-TTS 集成。前端 / API 不再返回该字段,迁移期间旧 job
    # 数据库里的 NULL/旧值会随 db 层 _parse_metadata_json 一起保留,不被删除。
    # metadata_json: dict | None = None  # noqa: E800 — Qwen3-TTS 字段(已注释)



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
    # 时间码 JSON 链接,与 JobStatus.timeline_url 同语义。
    timeline_url: str | None = None


SessionDetail.model_rebuild()


# ============================================================================
#  ⚠️ TTS 多角色对话合成(2025-Q3 引入,DISABLED / DEPRECATED)⚠️
# ----------------------------------------------------------------------------
# 当前版本(回退 Qwen3-TTS)所有 TTS 专用 Pydantic 模型用 `if False:` 包裹,
# 不再被 Pydantic 注册、不再被 main.py 引用(下方 main.py 的 import 也对应
# 注释)。后续恢复 Qwen3-TTS 集成时,把 `if False:` 改成 `if True:` 并在
# main.py 取消对应 from app.models import ... 行注释即可。
# ============================================================================

if False:  # noqa: E800 — Qwen3-TTS 模型块(已禁用)


    class FirstSegmentPreview(BaseModel):
        """ASR JSON 解析后给前端做预览用的首条非系统消息摘要。"""

        start_ms: int
        end_ms: int
        text: str


    class TtsImportPreview(BaseModel):
        """POST /api/tts/import-asr 响应:上传 + 解析 + 预览一次返回。

        前端拿到这个直接画预览页(总时长 / 角色数 / 各角色段数 / 首条台词),
        用户确认后再 POST /api/tts 真正入队。
        """

        file_id: str
        url: str  # /api/files/{file_id},前端可以直接 <audio> 引用
        segments_count: int
        total_duration_ms: int
        speakers: list[str]  # 唯一 speaker_id 列表(已剔除 __system__)
        speaker_segments: dict[str, int]  # speaker_id → 该角色段数
        first_segment_preview: FirstSegmentPreview | None = None


    class TtsSubmitRequest(BaseModel):
        """POST /api/tts 请求体:提交一次多角色对话合成任务。

        所有字段除 session_id / asr_file_id 外都可空:
          - 缺省 role_map / instructs → 用 backend/config/tts_voices.json(或内置默认);
          - 缺省 model_path → 用 TTS_MODEL_PATH 环境变量;
          - 缺省 target_sr / language → 用对应 env 默认。
        config_json 会把整个 body dump 后入 jobs 表,worker 端不再读请求体。
        """

        session_id: str
        asr_file_id: str
        role_map: dict[str, str] | None = None
        instructs: dict[str, str] | None = None
        model_path: str | None = None
        target_sr: int | None = None
        language: str | None = None


    class TtsFromJobRequest(BaseModel):
        """POST /api/tts/from-job 请求体:从已渲染视频任务派生 ASR → 入队 TTS 任务。

        后端拿到 source job_id 后:
          1) 校验存在 + user 所有权 + kind="render" + status="done"
          2) build_asr_from_dsl(config) → 落盘为 kind="asr" 的 files 行
          3) 入队 tts 任务,config_json 里塞 {"asr_file_id", "source_job_id",
             "role_map": {}, "instructs": {}}
        """

        job_id: str
