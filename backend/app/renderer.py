"""Jinja2 渲染 — 见 docs/04-template.md。"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models import ChatConfig, Message, auto_duration

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(("html", "j2")),
)


def load_template():
    return _env.get_template("wechat_chat.html.j2")


def build_participants(config: ChatConfig) -> list[dict]:
    """把参与者展平成模板需要的结构。"""
    return [
        {
            "id": p.id,
            "name": p.name,
            "avatar_url": p.avatar_url,
            "css_class": p.id,
        }
        for p in config.participants
    ]


def _is_self(config: ChatConfig, sender_id: str) -> bool:
    """消息方向规则(D3):
    - 单聊:participants[0] 视为"我",其消息走右侧
    - 群聊:仅 id == "me" 的参与者走右侧
    """
    if config.mode == "single":
        return config.participants[0].id == sender_id
    return sender_id == "me"


def build_messages(config: ChatConfig) -> list[dict]:
    """把消息列表展平成模板结构,加上 css_class / is_self / flash。"""
    by_id = {p.id: p for p in config.participants}
    out: list[dict] = []
    for i, m in enumerate(config.messages, start=1):
        if m.kind == "sys":
            out.append(
                {
                    "dom_id": f"m{i}",
                    "kind": "sys",
                    "sender_id": m.sender_id,
                    "sender_name": "",
                    "sender_avatar": None,
                    "text": m.text,
                    "image_url": None,
                    "css_class": "__system__",
                    "is_self": False,
                    "flash": "移出" in (m.text or ""),
                }
            )
        else:
            sender = by_id[m.sender_id]
            is_self = _is_self(config, m.sender_id)
            out.append(
                {
                    "dom_id": f"m{i}",
                    "kind": m.kind,
                    "sender_id": m.sender_id,
                    "sender_name": sender.name,
                    "sender_avatar": sender.avatar_url,
                    "text": m.text,
                    "image_url": m.image_url,
                    "css_class": "self" if is_self else "",
                    "is_self": is_self,
                    "flash": False,
                }
            )
    return out


def build_timeline(config: ChatConfig) -> list[dict]:
    """生成 TIMELINE 数组 — 见 docs/04-template.md §4.6。"""
    timeline: list[dict] = [{"id": "t1", "at": 500, "type": "stamp"}]
    t = 1200
    for i, m in enumerate(config.messages, start=1):
        timeline.append(
            {
                "id": f"m{i}",
                "at": t,
                "type": "sys" if m.kind == "sys" else "msg",
                "flash": m.kind == "sys" and "移出" in (m.text or ""),
            }
        )
        t += m.delay_ms
    return timeline


def resolve_duration_ms(config: ChatConfig) -> int:
    """总时长:用户显式传 duration_ms 则用用户值,否则自动算。"""
    if config.duration_ms is not None:
        return config.duration_ms
    return auto_duration(config.messages)


def render_template(config: ChatConfig) -> str:
    """渲染完整 HTML 文档字符串。预览与录制共用同一入口(D1)。"""
    tmpl = load_template()
    ctx = {
        "config": config,
        "title": config.title,
        "background": config.background,
        "participants": build_participants(config),
        "messages": build_messages(config),
        "timeline": build_timeline(config),
        "duration_ms": resolve_duration_ms(config),
    }
    return tmpl.render(**ctx)
