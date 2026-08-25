"""Jinja2 渲染 — 见 docs/04-template.md。"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.dsl import ChatScene, VideoDSL, auto_duration
from app.models import DISCLAIMER_CARD_TEXT, INTRO_EFFECTS, Message
from app.storage import BASE_URL

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

INTRO_DURATION_MS = 1800  # 扫描线开场特效持续时长
TYPEWRITER_INITIAL_MS = 200  # 打字机标题初始停顿
TYPEWRITER_PER_CHAR_MS = 180  # 打字机标题每个字符间隔
TYPEWRITER_FADE_MS = 300  # 打字机标题完成后淡出时长

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(("html", "j2")),
)


def load_template(name: str):
    return _env.get_template(f"{name}_chat.html.j2")


def resolve_upload_url(url: str | None) -> str | None:
    """把相对上传路径补成绝对 URL,方便 iframe / Playwright 加载。

    已是绝对 URL(http/https/data/file)或空值时原样返回;
    以 / 开头的相对路径会拼接 BASE_URL。
    """
    if not url:
        return url
    lower = url.lower()
    if lower.startswith(("http://", "https://", "data:", "file://")):
        return url
    if url.startswith("/"):
        return f"{BASE_URL}{url}"
    return f"{BASE_URL}/{url}"


def _avatar_rotation(id: str) -> float:
    """基于 id 生成确定性头像旋转角，范围 [-3, +3] 度。"""
    return float((sum(ord(c) for c in id) % 7) - 3)


def _seal_char(text: str | None) -> str:
    """系统消息印章文字：取 sys.text 首字；非 CJK 时回退固定"印"字。"""
    if text:
        first = text[0]
        if "\u4e00" <= first <= "\u9fff":
            return first
    return "印"


def resolve_intro_duration_ms(config: ChatScene) -> int:
    """根据 intro_effect 与标题长度计算开场特效实际时长。

    - typewriter: 初始停顿 + 逐字间隔 + 淡出
    - scanline: 固定 INTRO_DURATION_MS
    - none: 0
    """
    if config.intro_effect == "none":
        return 0
    if config.intro_effect == "typewriter":
        chars = len(config.title or "")
        return TYPEWRITER_INITIAL_MS + chars * TYPEWRITER_PER_CHAR_MS + TYPEWRITER_FADE_MS
    return INTRO_DURATION_MS


def build_participants(config: ChatScene) -> list[dict]:
    """把参与者展平成模板需要的结构;头像 URL 补成绝对路径。"""
    return [
        {
            "id": p.id,
            "name": p.name,
            "avatar_url": resolve_upload_url(p.avatar_url),
            "persona": p.persona,
            "css_class": p.id,
            "avatar_rotation": _avatar_rotation(p.id),
        }
        for p in config.participants
    ]


def _default_is_self(config: ChatScene, sender_id: str) -> bool:
    """消息方向默认规则(D3):
    - 单聊:participants[0] 视为"我",其消息走右侧
    - 群聊:仅 id == "me" 的参与者走右侧
    """
    if config.mode == "single":
        return config.participants[0].id == sender_id
    return sender_id == "me"


def _is_self(config: ChatScene, message: Message) -> bool:
    """返回消息是否走右侧;若消息显式指定 align 则优先使用,否则按默认规则推断。"""
    if message.align == "right":
        return True
    if message.align == "left":
        return False
    return _default_is_self(config, message.sender_id)


def build_messages(config: ChatScene) -> list[dict]:
    """把消息列表展平成模板结构,加上 css_class / is_self / flash / show_avatar / reply_to_*。"""
    by_id = {p.id: p for p in config.participants}

    def _reply_info(current_idx: int) -> dict[str, str | None]:
        """计算当前消息的回复引用信息;无效时全返回 None。"""
        m = config.messages[current_idx]
        reply_to = m.reply_to
        if reply_to is None:
            return {"reply_to_dom_id": None, "reply_to_sender_name": None, "reply_to_text": None}
        # 1-based 序号必须指向当前消息之前,且不能是 sys/timestamp
        if reply_to < 1 or reply_to >= current_idx + 1 or reply_to > len(config.messages):
            return {"reply_to_dom_id": None, "reply_to_sender_name": None, "reply_to_text": None}
        target = config.messages[reply_to - 1]
        if target.kind in {"sys", "timestamp"}:
            return {"reply_to_dom_id": None, "reply_to_sender_name": None, "reply_to_text": None}
        target_sender = by_id.get(target.sender_id)
        text = (target.text or "").split("\n", 1)[0]
        return {
            "reply_to_dom_id": f"m{reply_to}",
            "reply_to_sender_name": target_sender.name if target_sender else "",
            "reply_to_text": text,
        }

    out: list[dict] = []
    for i, m in enumerate(config.messages, start=1):
        reply = _reply_info(i - 1)
        if m.kind == "sys":
            out.append(
                {
                    "dom_id": f"m{i}",
                    "kind": "sys",
                    "sender_id": m.sender_id,
                    "sender_name": "",
                    "sender_avatar": None,
                    "sender_avatar_rotation": 0.0,
                    "seal_char": _seal_char(m.text),
                    "persona": None,
                    "text": m.text,
                    "image_url": None,
                    "video_url": None,
                    "cover_url": None,
                    "duration": None,
                    "css_class": "__system__",
                    "is_self": False,
                    "flash": False,
                    "show_avatar": False,
                    "show_name": False,
                    **reply,
                }
            )
            continue

        if m.kind == "timestamp":
            out.append(
                {
                    "dom_id": f"m{i}",
                    "kind": "timestamp",
                    "sender_id": m.sender_id,
                    "sender_name": "",
                    "sender_avatar": None,
                    "sender_avatar_rotation": 0.0,
                    "persona": None,
                    "text": m.text,
                    "image_url": None,
                    "video_url": None,
                    "cover_url": None,
                    "duration": None,
                    "css_class": "__timestamp__",
                    "is_self": False,
                    "flash": False,
                    "show_avatar": False,
                    "show_name": False,
                    **reply,
                }
            )
            continue

        sender = by_id[m.sender_id]
        is_self = _is_self(config, m)
        out.append(
            {
                "dom_id": f"m{i}",
                "kind": m.kind,
                "sender_id": m.sender_id,
                "sender_name": sender.name,
                "sender_avatar": resolve_upload_url(sender.avatar_url),
                "sender_avatar_rotation": _avatar_rotation(m.sender_id),
                "persona": sender.persona,
                "text": m.text,
                "image_url": resolve_upload_url(m.image_url),
                "video_url": resolve_upload_url(m.video_url),
                "cover_url": resolve_upload_url(m.cover_url),
                "duration": m.duration,
                "css_class": "self" if is_self else "",
                "is_self": is_self,
                "flash": False,
                "show_avatar": True,
                "show_name": not is_self,
                **reply,
            }
        )
    return out


def build_timeline(config: ChatScene, intro_duration_ms: int | None = None) -> list[dict]:
    """生成 TIMELINE 数组 — 开头固定 1s AI 声明卡,可选 intro 特效,然后按消息 delay 推进。"""
    timeline: list[dict] = [{"id": "__disclaimer__", "at": 0, "type": "disclaimer"}]
    if intro_duration_ms is None:
        intro_duration_ms = resolve_intro_duration_ms(config)
    intro_duration = intro_duration_ms if config.intro_effect != "none" else 0
    start_idx = 0
    t = 1000 + intro_duration  # 声明卡显示 1s,再播放 intro,之后显示第一条消息

    if intro_duration:
        timeline.append(
            {"id": "__intro__", "at": 1000, "type": "intro", "effect": config.intro_effect}
        )

    first_msg = config.messages[0] if config.messages else None
    if first_msg and first_msg.kind == "timestamp" and first_msg.text:
        timeline.append({"id": "m1", "at": t, "type": "timestamp"})
        start_idx = 1
        t += 700

    for i, m in enumerate(config.messages[start_idx:], start=start_idx + 1):
        timeline.append(
            {
                "id": f"m{i}",
                "at": t,
                "type": (
                    "sys"
                    if m.kind == "sys"
                    else "timestamp" if m.kind == "timestamp" else "msg"
                ),
                "flash": False,
            }
        )
        t += m.delay_ms
    return timeline


def build_timeline_with_durations(
    config: ChatScene,
    intro_duration_ms: int | None = None,
    total_duration_ms: int | None = None,
) -> list[dict]:
    """在 `build_timeline()` 基础上给每条事件算 `appeared_at` / `disappeared_at`(毫秒,相对视频起点 0)。

    消失语义:
      - 下一条事件出现时,上一条立即消失(对应模板里"新消息把上一条顶出聊天区"的视觉);
      - 最后一条事件(`disclaimer` / `intro` / 末条消息)在场景总时长 `total_duration_ms`
        处消失,留出结尾缓冲。

    不复用 `build_timeline()` 返回值是为了:
      (a) 每条事件额外携带 `kind` / `sender_id` / `sender_name` / `text` / `image_url`
          / `video_url` / `duration` 等渲染模板字段(取自 `build_messages`),前端做表格展示
          时不需要再翻 DSL;
      (b) 消失时刻需要 `total_duration_ms`(场景结束),而 `build_timeline` 只返回
          "at",没有"末尾"信息,合并实现更直观。

    与 `build_timeline()` 的 `at` 字段完全一致 — 同一个事件出现时刻相同,只是新增
    `appeared_at` / `disappeared_at` / `duration_ms` / `sender_id` / `sender_name` /
    `summary` 等展示用字段。**不修改** `build_timeline` 的现有签名和返回值,旧
    调用方零影响。

    参数:
      - `config`: 当前 ChatScene
      - `intro_duration_ms`: 可显式传入;None 时按 `config.intro_effect` 自动算
      - `total_duration_ms`: 场景总时长;None 时按 `resolve_duration_ms` 算(与
        `render_dsl` 同一公式,保证 timeline 与产物视频完全对齐)
    """
    if intro_duration_ms is None:
        intro_duration_ms = resolve_intro_duration_ms(config)
    if total_duration_ms is None:
        total_duration_ms = resolve_duration_ms(config, intro_duration_ms)

    intro_duration = intro_duration_ms if config.intro_effect != "none" else 0

    # 先按 build_messages 的顺序拿到每条消息的展示字段,方便 timeline 直接引用
    rendered_msgs = build_messages(config)

    events: list[dict] = []

    # __disclaimer__:at=0 显示,1000ms 后消失(让位给 intro / 首条消息)
    events.append(
        {
            "id": "__disclaimer__",
            "at": 0,
            "type": "disclaimer",
            "kind": "disclaimer",
            "sender_id": "__system__",
            "sender_name": "",
            "summary": DISCLAIMER_CARD_TEXT,
            "text": DISCLAIMER_CARD_TEXT,
            "image_url": None,
            "video_url": None,
            "duration": None,
        }
    )

    t = 1000 + intro_duration  # 声明卡 1s 后开始第一条非声明事件
    first_msg = config.messages[0] if config.messages else None

    if intro_duration:
        events.append(
            {
                "id": "__intro__",
                "at": 1000,
                "type": "intro",
                "kind": "intro",
                "sender_id": "__system__",
                "sender_name": "",
                "summary": config.intro_effect,
                "text": config.intro_effect,
                "image_url": None,
                "video_url": None,
                "duration": None,
            }
        )

    start_idx = 0
    if first_msg and first_msg.kind == "timestamp" and first_msg.text:
        events.append(_msg_event(f"m1", t, rendered_msgs[0]))
        start_idx = 1
        t += 700

    for i, m in enumerate(config.messages[start_idx:], start=start_idx + 1):
        events.append(_msg_event(f"m{i}", t, rendered_msgs[i - 1]))
        t += m.delay_ms

    # 第二轮:按顺序算 disappeared_at = 下一条 at;最后一条 = total_duration_ms
    for idx, ev in enumerate(events):
        appeared = ev["at"]
        if idx + 1 < len(events):
            disappeared = events[idx + 1]["at"]
        else:
            disappeared = total_duration_ms
        ev["appeared_at"] = appeared
        ev["disappeared_at"] = disappeared
        ev["duration_ms"] = max(0, disappeared - appeared)
    return events


def _msg_event(dom_id: str, at_ms: int, rendered_msg: dict) -> dict:
    """把 build_messages 的单条 dict 转成 timeline 事件(出现时刻 + 展示字段)。"""
    kind = rendered_msg.get("kind", "text")
    if kind == "sys":
        type_label = "sys"
    elif kind == "timestamp":
        type_label = "timestamp"
    else:
        type_label = "msg"
    return {
        "id": dom_id,
        "at": at_ms,
        "type": type_label,
        "kind": kind,
        "sender_id": rendered_msg.get("sender_id", ""),
        "sender_name": rendered_msg.get("sender_name", ""),
        "summary": _summarize_message(rendered_msg),
        "text": rendered_msg.get("text"),
        "image_url": rendered_msg.get("image_url"),
        "video_url": rendered_msg.get("video_url"),
        "duration": rendered_msg.get("duration"),
    }


def _summarize_message(rendered_msg: dict) -> str:
    """给前端表格用的简短摘要:文字取首行,图片 / 视频 / emoji 给类型提示。"""
    kind = rendered_msg.get("kind", "")
    text = rendered_msg.get("text")
    if kind == "image":
        return f"[图片] {text or ''}".strip()
    if kind == "video":
        return f"[视频] {text or ''}".strip()
    if kind == "emoji":
        return text or "[emoji]"
    if kind == "sys":
        return text or ""
    if kind == "timestamp":
        return text or ""
    if text:
        return text.split("\n", 1)[0]
    return ""


def resolve_duration_ms(config: ChatScene, intro_duration_ms: int | None = None) -> int:
    """总时长:用户显式传 duration_ms 则用用户值,否则自动算(含 1s 声明卡 + intro 时长)。"""
    if config.duration_ms is not None:
        return config.duration_ms
    if intro_duration_ms is None:
        intro_duration_ms = resolve_intro_duration_ms(config)
    intro_duration = intro_duration_ms if config.intro_effect != "none" else 0
    first_msg = config.messages[0] if config.messages else None
    first_delay_ms = 1000 + intro_duration
    if first_msg and first_msg.kind == "timestamp":
        first_delay_ms += 700
    return auto_duration(config.messages, first_delay_ms=first_delay_ms)


def render_chat(scene: ChatScene, template: str) -> str:
    """渲染对话剧场场景 HTML。预览与录制共用同一入口。"""
    tmpl = load_template(template)
    intro_duration_ms = resolve_intro_duration_ms(scene)
    ctx = {
        "config": scene,
        "mode": scene.mode,
        "title": scene.title,
        "background": scene.background,
        "background_image_url": resolve_upload_url(scene.background_image_url),
        "background_visible": scene.background_visible,
        "opacity": scene.opacity,
        "style_theme": scene.style_theme,
        "intent_label": scene.intent,
        "participants": build_participants(scene),
        "messages": build_messages(scene),
        "timeline": build_timeline(scene, intro_duration_ms),
        "duration_ms": resolve_duration_ms(scene, intro_duration_ms),
        "disclaimer_text": DISCLAIMER_CARD_TEXT,
        "ai_badge_style": scene.watermark.badge_style,
        "watermark_text": scene.watermark.text,
        "intro_effect": scene.intro_effect,
        "intro_duration_ms": intro_duration_ms,
        "typewriter_initial_ms": TYPEWRITER_INITIAL_MS,
        "typewriter_per_char_ms": TYPEWRITER_PER_CHAR_MS,
    }
    return tmpl.render(**ctx)


def render_dsl(dsl: VideoDSL) -> str:
    """按 kind + template 分发渲染。"""
    if dsl.kind != "chat":
        raise ValueError(f"unsupported dsl kind: {dsl.kind}")
    if dsl.template not in ("cyberpunk", "watercolor", "pixel", "comic", "noir", "ink", "green_screen"):
        raise ValueError(f"unsupported chat template: {dsl.template}")
    return render_chat(dsl.scene, dsl.template)
