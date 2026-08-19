"""Jinja2 渲染 — 见 docs/04-template.md。"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.dsl import ChatScene, VideoDSL, auto_duration
from app.models import Message

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(("html", "j2")),
)


def load_template():
    return _env.get_template("wechat_chat.html.j2")


def build_participants(config: ChatScene) -> list[dict]:
    """把参与者展平成模板需要的结构。"""
    return [
        {
            "id": p.id,
            "name": p.name,
            "avatar_url": p.avatar_url,
            "label": p.label,
            "css_class": p.id,
        }
        for p in config.participants
    ]


def _is_self(config: ChatScene, sender_id: str) -> bool:
    """消息方向规则(D3):
    - 单聊:participants[0] 视为"我",其消息走右侧
    - 群聊:仅 id == "me" 的参与者走右侧
    """
    if config.mode == "single":
        return config.participants[0].id == sender_id
    return sender_id == "me"


def build_messages(config: ChatScene) -> list[dict]:
    """把消息列表展平成模板结构,加上 css_class / is_self / flash / show_avatar。"""
    by_id = {p.id: p for p in config.participants}
    out: list[dict] = []
    prev_chat_sender: str | None = None
    for i, m in enumerate(config.messages, start=1):
        if m.kind == "sys":
            out.append(
                {
                    "dom_id": f"m{i}",
                    "kind": "sys",
                    "sender_id": m.sender_id,
                    "sender_name": "",
                    "sender_avatar": None,
                    "label": None,
                    "text": m.text,
                    "image_url": None,
                    "video_url": None,
                    "cover_url": None,
                    "duration": None,
                    "css_class": "__system__",
                    "is_self": False,
                    "flash": "移出" in (m.text or ""),
                    "show_avatar": False,
                    "show_name": False,
                }
            )
            prev_chat_sender = None
            continue

        if m.kind == "timestamp":
            out.append(
                {
                    "dom_id": f"m{i}",
                    "kind": "timestamp",
                    "sender_id": m.sender_id,
                    "sender_name": "",
                    "sender_avatar": None,
                    "label": None,
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
                }
            )
            prev_chat_sender = None
            continue

        sender = by_id[m.sender_id]
        is_self = _is_self(config, m.sender_id)
        show_sender = m.sender_id != prev_chat_sender
        prev_chat_sender = m.sender_id
        out.append(
            {
                "dom_id": f"m{i}",
                "kind": m.kind,
                "sender_id": m.sender_id,
                "sender_name": sender.name,
                "sender_avatar": sender.avatar_url,
                "label": sender.label,
                "text": m.text,
                "image_url": m.image_url,
                "video_url": m.video_url,
                "cover_url": m.cover_url,
                "duration": m.duration,
                "css_class": "self" if is_self else "",
                "is_self": is_self,
                "flash": False,
                "show_avatar": show_sender,
                "show_name": show_sender and not is_self,
            }
        )
    return out


def build_timeline(config: ChatScene) -> list[dict]:
    """生成 TIMELINE 数组 — 见 docs/04-template.md §4.6。"""
    # 如果用户第一条就是 timestamp,则用它的内容替换默认时间戳
    first_msg = config.messages[0] if config.messages else None
    if first_msg and first_msg.kind == "timestamp" and first_msg.text:
        timeline: list[dict] = [{"id": "m1", "at": 500, "type": "timestamp"}]
        start_idx = 1
        t = 1200
    else:
        timeline = [{"id": "t1", "at": 500, "type": "stamp"}]
        start_idx = 0
        t = 1200

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
                "flash": m.kind == "sys" and "移出" in (m.text or ""),
            }
        )
        t += m.delay_ms
    return timeline


def resolve_duration_ms(config: ChatScene) -> int:
    """总时长:用户显式传 duration_ms 则用用户值,否则自动算。"""
    if config.duration_ms is not None:
        return config.duration_ms
    return auto_duration(config.messages)


def render_chat_wechat(scene: ChatScene) -> str:
    """渲染微信聊天场景 HTML。预览与录制共用同一入口(D1)。"""
    tmpl = load_template()
    ctx = {
        "config": scene,
        "mode": scene.mode,
        "title": scene.title,
        "subtitle": scene.subtitle,
        "background": scene.background,
        "background_image_url": scene.background_image_url,
        "status_bar": scene.status_bar,
        "member_count": scene.member_count,
        "muted": scene.muted,
        "participants": build_participants(scene),
        "messages": build_messages(scene),
        "timeline": build_timeline(scene),
        "duration_ms": resolve_duration_ms(scene),
    }
    return tmpl.render(**ctx)


def render_dsl(dsl: VideoDSL) -> str:
    """按 kind + template 分发渲染。"""
    if dsl.kind != "chat":
        raise ValueError(f"unsupported dsl kind: {dsl.kind}")
    if dsl.template == "wechat":
        return render_chat_wechat(dsl.scene)
    raise ValueError(f"unsupported chat template: {dsl.template}")
