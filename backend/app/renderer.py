"""Jinja2 渲染 — 见 docs/04-template.md。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.dsl import ChatScene, VideoDSL, auto_duration
from app.models import Message
from app.storage import BASE_URL

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
ICONS_DIR = Path(__file__).parent / "assets" / "icons" / "status-bar"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(("html", "j2")),
)


@lru_cache(maxsize=None)
def _read_svg(filename: str) -> str:
    """读取状态栏图标 SVG 文件(仅一次,后续走缓存)。"""
    path = ICONS_DIR / filename
    if not path.is_file():
        return ""
    raw = path.read_text(encoding="utf-8")
    # 去掉 XML 声明与 xmlns 重复属性,保留 <svg> 根节点,直接插入 JSX 即可
    if raw.startswith("<?xml"):
        raw = raw.split("?>", 1)[1].lstrip()
    return raw.strip()


@lru_cache(maxsize=None)
def _load_status_bar_icons() -> dict[str, str]:
    """加载状态栏所需的全部 SVG 串,按用途命名。"""
    static_icons = {
        "bluetooth": _read_svg("bluetooth-24.svg"),
        "wifi": _read_svg("wifi-24.svg"),
        "alarm": _read_svg("alarm-24.svg"),
    }
    # 电池 0-10 动态映射
    for n in range(11):
        static_icons[f"battery_{n}"] = _read_svg(f"battery-{n}.svg")
    return static_icons


def load_template():
    return _env.get_template("wechat_chat.html.j2")


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


def build_participants(config: ChatScene) -> list[dict]:
    """把参与者展平成模板需要的结构;头像 URL 补成绝对路径。"""
    return [
        {
            "id": p.id,
            "name": p.name,
            "avatar_url": resolve_upload_url(p.avatar_url),
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
            continue

        sender = by_id[m.sender_id]
        is_self = _is_self(config, m.sender_id)
        out.append(
            {
                "dom_id": f"m{i}",
                "kind": m.kind,
                "sender_id": m.sender_id,
                "sender_name": sender.name,
                "sender_avatar": resolve_upload_url(sender.avatar_url),
                "label": sender.label,
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
            }
        )
    return out


def build_timeline(config: ChatScene) -> list[dict]:
    """生成 TIMELINE 数组 — 见 docs/04-template.md §4.6。"""
    timeline: list[dict] = []
    start_idx = 0
    t = 500  # 第一条消息显示时间

    first_msg = config.messages[0] if config.messages else None
    if first_msg and first_msg.kind == "timestamp" and first_msg.text:
        timeline.append({"id": "m1", "at": t, "type": "timestamp"})
        start_idx = 1
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
    first_msg = config.messages[0] if config.messages else None
    first_delay_ms = 1200 if first_msg and first_msg.kind == "timestamp" else 500
    return auto_duration(config.messages, first_delay_ms=first_delay_ms)


def render_chat_wechat(scene: ChatScene) -> str:
    """渲染微信聊天场景 HTML。预览与录制共用同一入口(D1)。"""
    tmpl = load_template()
    # 电池电量 0-100 → battery index 0-10,用于挑选用哪张 SVG
    battery_idx = max(0, min(10, round(scene.status_bar.battery_level / 10)))
    ctx = {
        "config": scene,
        "mode": scene.mode,
        "title": scene.title,
        "subtitle": scene.subtitle,
        "background": scene.background,
        "background_image_url": resolve_upload_url(scene.background_image_url),
        "opacity": scene.opacity,
        "status_bar": scene.status_bar,
        "member_count": scene.member_count,
        "muted": scene.muted,
        "participants": build_participants(scene),
        "messages": build_messages(scene),
        "timeline": build_timeline(scene),
        "duration_ms": resolve_duration_ms(scene),
        "icons": _load_status_bar_icons(),
        "battery_icon": f"battery_{battery_idx}",
    }
    return tmpl.render(**ctx)


def render_dsl(dsl: VideoDSL) -> str:
    """按 kind + template 分发渲染。"""
    if dsl.kind != "chat":
        raise ValueError(f"unsupported dsl kind: {dsl.kind}")
    if dsl.template == "wechat":
        return render_chat_wechat(dsl.scene)
    raise ValueError(f"unsupported chat template: {dsl.template}")
