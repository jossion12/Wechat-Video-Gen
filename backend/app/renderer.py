"""Jinja2 渲染 — 见 docs/04-template.md。"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.dsl import ChatScene, VideoDSL, auto_duration
from app.models import DISCLAIMER_CARD_TEXT, Message
from app.storage import BASE_URL

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

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


def build_timeline(config: ChatScene) -> list[dict]:
    """生成 TIMELINE 数组 — 开头固定 1s AI 声明卡,然后按消息 delay 推进。"""
    timeline: list[dict] = [{"id": "__disclaimer__", "at": 0, "type": "disclaimer"}]
    start_idx = 0
    t = 1000  # 声明卡显示 1s,第一条消息在 1s 后显示

    first_msg = config.messages[0] if config.messages else None
    if first_msg and first_msg.kind == "timestamp" and first_msg.text:
        timeline.append({"id": "m1", "at": t, "type": "timestamp"})
        start_idx = 1
        t = 1700

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


def resolve_duration_ms(config: ChatScene) -> int:
    """总时长:用户显式传 duration_ms 则用用户值,否则自动算(含 1s 声明卡)。"""
    if config.duration_ms is not None:
        return config.duration_ms
    first_msg = config.messages[0] if config.messages else None
    first_delay_ms = 1700 if first_msg and first_msg.kind == "timestamp" else 1000
    return auto_duration(config.messages, first_delay_ms=first_delay_ms)


def render_chat(scene: ChatScene, template: str) -> str:
    """渲染对话剧场场景 HTML。预览与录制共用同一入口。"""
    tmpl = load_template(template)
    ctx = {
        "config": scene,
        "mode": scene.mode,
        "title": scene.title,
        "background": scene.background,
        "background_image_url": resolve_upload_url(scene.background_image_url),
        "opacity": scene.opacity,
        "style_theme": scene.style_theme,
        "intent_label": scene.intent,
        "participants": build_participants(scene),
        "messages": build_messages(scene),
        "timeline": build_timeline(scene),
        "duration_ms": resolve_duration_ms(scene),
        "disclaimer_text": DISCLAIMER_CARD_TEXT,
        "ai_badge_style": scene.watermark.badge_style,
        "watermark_text": scene.watermark.text,
    }
    return tmpl.render(**ctx)


def render_dsl(dsl: VideoDSL) -> str:
    """按 kind + template 分发渲染。"""
    if dsl.kind != "chat":
        raise ValueError(f"unsupported dsl kind: {dsl.kind}")
    if dsl.template not in ("cyberpunk", "watercolor", "pixel", "comic", "noir", "ink"):
        raise ValueError(f"unsupported chat template: {dsl.template}")
    return render_chat(dsl.scene, dsl.template)
