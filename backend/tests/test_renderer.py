"""模板渲染测试 — 见 docs/04-template.md §4.10、docs/06-acceptance.md CODE-3。"""

from __future__ import annotations

import json
import re

import pytest
from pydantic import ValidationError

from app.models import ChatConfig, Message, Participant, auto_duration
from app.renderer import (
    build_timeline,
    render_template,
    resolve_duration_ms,
)


def make_config(**overrides) -> ChatConfig:
    participants = [
        Participant(id="me", name="我", avatar_url=None),
        Participant(id="her", name="她", avatar_url=None),
    ]
    messages = [
        Message(sender_id="me", kind="text", text="在吗", delay_ms=1500),
        Message(sender_id="her", kind="text", text="嗯", delay_ms=1500),
        Message(sender_id="me", kind="text", text="周末吃饭?", delay_ms=1500),
    ]
    base = dict(mode="single", participants=participants, messages=messages)
    base.update(overrides)
    return ChatConfig(**base)


# ---- 4.10 模板测试 ----

def test_minimal_config_renders_valid_html():
    """✅ 最小配置(2 参与者 / 1 文本消息)能渲染出合法 HTML。"""
    cfg = make_config(
        messages=[Message(sender_id="her", kind="text", text="你好", delay_ms=1500)]
    )
    html = render_template(cfg)
    assert html.strip().startswith("<!DOCTYPE html>")
    assert "<html" in html and "</html>" in html
    assert "<body" in html and "</body>" in html
    assert "你好" in html
    assert 'id="m1"' in html
    assert "wechat" in html.lower()


def _has_class(html: str, tag: str, dom_id: str, klass: str) -> bool:
    """辅助:在 html 里查找 tag 且 id=dom_id 且 class 包含 klass 的元素。"""
    return bool(
        re.search(
            rf'<{tag}\s+class="[^"]*\b{re.escape(klass)}\b[^"]*"\s+id="{dom_id}"',
            html,
        )
    )


def test_single_mode_self_class():
    """✅ 单聊模式"自己"消息带 `.msg.self`。"""
    html = render_template(make_config())
    # m1 / m3 是我发的(右侧),m2 是她的(左侧)
    assert _has_class(html, "div", "m1", "self")
    assert _has_class(html, "div", "m2", "msg")
    assert _has_class(html, "div", "m3", "self")


def test_image_message_generates_img():
    """✅ 图片消息生成 `<img>` 标签。"""
    cfg = make_config(
        messages=[
            Message(
                sender_id="me",
                kind="image",
                image_url="/uploads/plum.jpg",
                text="倚梅园的梅花开了。",
                delay_ms=1500,
            )
        ]
    )
    html = render_template(cfg)
    assert '<img src="/uploads/plum.jpg"' in html
    assert "倚梅园的梅花开了。" in html


def test_sys_message_no_avatar_and_flash():
    """✅ 系统消息不显示头像;含"移出"时带 flash 红色脉冲。"""
    cfg = make_config(
        messages=[
            Message(
                sender_id="__system__", kind="sys", text="余答应已被移出群聊", delay_ms=1500
            )
        ]
    )
    html = render_template(cfg)
    assert re.search(r'class="sys-msg\b', html)
    assert 'class="avatar' not in html  # 系统消息无头像
    timeline = build_timeline(cfg)
    assert timeline[-1]["type"] == "sys"
    assert timeline[-1]["flash"] is True
    assert "flash" in html  # CSS 里定义了 flash 动画


def test_timeline_json_parses():
    """✅ TIMELINE JSON 合法可被 JSON.parse 解析。"""
    cfg = make_config()
    html = render_template(cfg)
    m = re.search(r"const TIMELINE = (\[.*?\]);", html, re.S)
    assert m, "TIMELINE not found in rendered html"
    parsed = json.loads(m.group(1))
    assert parsed[0] == {"id": "t1", "at": 500, "type": "stamp"}
    ids = [t["id"] for t in parsed]
    assert ids == ["t1", "m1", "m2", "m3"]
    # 时间轴递增
    ats = [t["at"] for t in parsed]
    assert ats == sorted(ats)


def test_text_message_requires_text():
    """✅ 缺少 text 的 text 类消息报错(含纯空白)。"""
    for bad in (None, "", "   "):
        with pytest.raises(ValidationError):
            make_config(
                messages=[Message(sender_id="her", kind="text", text=bad, delay_ms=1500)]
            )


def test_missing_avatar_uses_default_placeholder():
    """✅ 缺头像 URL 的消息用默认占位图(灰色 div)。"""
    cfg = make_config(
        participants=[
            Participant(id="me", name="我", avatar_url=None),
            Participant(id="her", name="她", avatar_url=None),
        ]
    )
    html = render_template(cfg)
    assert 'class="avatar avatar-default"' in html


def test_avatar_url_inlined_when_present():
    """✅ 有头像 URL 时内联 background-image。"""
    cfg = make_config(
        participants=[
            Participant(id="me", name="我", avatar_url="/uploads/me.png"),
            Participant(id="her", name="她", avatar_url=None),
        ]
    )
    html = render_template(cfg)
    assert "background-image: url('/uploads/me.png')" in html


def test_background_image_url_rendered():
    """✅ 设置 background_image_url 时内联整页背景图,并保留颜色兜底。"""
    cfg = make_config(background_image_url="/uploads/bg.png")
    html = render_template(cfg)
    assert "background: #ededed" in html  # 颜色兜底仍在
    assert "background-image: url('/uploads/bg.png')" in html
    assert "background-size: cover" in html
    assert "background-position: center" in html


def test_no_background_image_renders_plain_color():
    """✅ 未设置 background_image_url 时不输出背景图样式。"""
    html = render_template(make_config())
    assert "background: #ededed" in html
    assert "background-image: url(" not in html


# ---- 时长 / 方向规则 / 校验 ----

def test_auto_duration_formula():
    """PERF-1:5 条消息 delay=1500 → 1200 + 5*1500 + 1500 = 10200。"""
    msgs = [
        Message(sender_id="me", kind="text", text="x", delay_ms=1500) for _ in range(5)
    ]
    assert auto_duration(msgs) == 10200
    cfg = make_config(messages=msgs)
    assert resolve_duration_ms(cfg) == 10200


def test_explicit_duration_wins():
    """✅ 用户显式 duration_ms 覆盖自动时长。"""
    cfg = make_config(duration_ms=30000)
    assert resolve_duration_ms(cfg) == 30000


def test_group_me_message_on_right():
    """✅ 群聊中 id=='me' 的参与者消息走右侧。"""
    cfg = ChatConfig(
        mode="group",
        participants=[
            Participant(id="me", name="我"),
            Participant(id="bob", name="Bob"),
        ],
        messages=[Message(sender_id="me", kind="text", text="在吗", delay_ms=1500)],
    )
    html = render_template(cfg)
    assert _has_class(html, "div", "m1", "self")


def test_group_other_message_on_left():
    """✅ 群聊中非 me 的消息走左侧白底。"""
    cfg = ChatConfig(
        mode="group",
        participants=[
            Participant(id="me", name="我"),
            Participant(id="bob", name="Bob"),
        ],
        messages=[Message(sender_id="bob", kind="text", text="在吗", delay_ms=1500)],
    )
    html = render_template(cfg)
    assert _has_class(html, "div", "m1", "msg")


def test_first_message_delay_minimum():
    """✅ 第一条消息 delay_ms < 500 报错。"""
    with pytest.raises(ValidationError):
        make_config(
            messages=[
                Message(sender_id="me", kind="text", text="在吗", delay_ms=300)
            ]
        )


def test_unknown_sender_rejected():
    """✅ sender_id 必须匹配某个参与者。"""
    with pytest.raises(ValidationError):
        make_config(
            messages=[
                Message(sender_id="zzz", kind="text", text="在吗", delay_ms=1500)
            ]
        )


def test_negative_duration_rejected():
    """PERF-3:duration_ms=-1 → 422。"""
    with pytest.raises(ValidationError):
        make_config(duration_ms=-1)


def test_single_mode_accepts_three_participants():
    """✅ 单聊不限制恰好 2 人:participants[0] 为"我",其余走左侧(切换模式不破坏预览)。"""
    cfg = ChatConfig(
        mode="single",
        participants=[
            Participant(id="me", name="我"),
            Participant(id="a", name="A"),
            Participant(id="b", name="B"),
        ],
        messages=[
            Message(sender_id="me", kind="text", text="在吗", delay_ms=1500),
            Message(sender_id="b", kind="text", text="你好", delay_ms=1500),
        ],
    )
    html = render_template(cfg)
    assert _has_class(html, "div", "m1", "self")  # me 在右侧
    assert _has_class(html, "div", "m2", "msg")  # b 在左侧


def test_requires_at_least_two_participants():
    """✅ 参与者少于 2 个报错(与模式无关)。"""
    with pytest.raises(ValidationError):
        ChatConfig(
            mode="single",
            participants=[Participant(id="a", name="A")],
            messages=[Message(sender_id="a", kind="text", text="x", delay_ms=1500)],
        )
    with pytest.raises(ValidationError):
        ChatConfig(
            mode="group",
            participants=[Participant(id="a", name="A")],
            messages=[Message(sender_id="a", kind="text", text="x", delay_ms=1500)],
        )


# ---- 新增:状态栏 / 头部 / 视频 / 表情 / 时间戳 / 合并头像 ----

from app.models import StatusBar


def test_status_bar_rendered():
    """✅ 状态栏时间、网速、双卡、电池、图标可配置。"""
    cfg = make_config(
        status_bar=StatusBar(
            time="00:00",
            battery_level=61,
            network_speed="3.5 K/s",
            signal_type="5A",
            dual_sim=True,
            show_bluetooth=True,
            show_alarm=True,
            show_nfc=True,
            app_icons=["bilibili"],
        )
    )
    html = render_template(cfg)
    assert "00:00" in html
    assert "3.5 K/s" in html
    assert "5A" in html
    assert 'width: 61%;' in html
    assert "icon-bluetooth" in html
    assert "icon-alarm" in html
    assert "icon-nfc" in html


def test_single_subtitle_rendered():
    """✅ 单聊副标题显示在标题下方。"""
    cfg = make_config(mode="single", subtitle="云熙数码")
    html = render_template(cfg)
    assert 'class="subtitle"' in html
    assert "云熙数码" in html


def test_group_member_count_and_mute_bell():
    """✅ 群聊人数和免打扰铃铛显示在头部。"""
    cfg = ChatConfig(
        mode="group",
        title="测试群",
        member_count=221,
        muted=True,
        participants=[
            Participant(id="me", name="我"),
            Participant(id="bob", name="Bob"),
        ],
        messages=[Message(sender_id="bob", kind="text", text="hi", delay_ms=1500)],
    )
    html = render_template(cfg)
    assert "(221)" in html
    assert 'class="mute-bell"' in html


def test_participant_label_rendered():
    """✅ 参与者 label 在群聊昵称旁显示。"""
    cfg = ChatConfig(
        mode="group",
        participants=[
            Participant(id="me", name="我"),
            Participant(id="bob", name="Bob", label="【OPC圈成都】"),
        ],
        messages=[Message(sender_id="bob", kind="text", text="hi", delay_ms=1500)],
    )
    html = render_template(cfg)
    assert "【OPC圈成都】" in html


def test_timestamp_message():
    """✅ timestamp 消息渲染为时间分隔线,不占用聊天头像。"""
    cfg = make_config(
        messages=[
            Message(sender_id="__system__", kind="timestamp", text="星期五 18:27", delay_ms=1500),
            Message(sender_id="her", kind="text", text="你好", delay_ms=1500),
        ]
    )
    html = render_template(cfg)
    assert 'class="time-stamp"' in html
    assert "星期五 18:27" in html
    # 时间戳消息 m1 本身不含头像
    m1_match = re.search(r'<div class="time-stamp" id="m1"[^>]*>.*?</div>', html, re.S)
    assert m1_match
    assert 'class="avatar' not in m1_match.group(0)


def test_video_message():
    """✅ video 消息渲染带播放按钮和时长。"""
    cfg = make_config(
        messages=[
            Message(
                sender_id="her",
                kind="video",
                video_url="/uploads/video.mp4",
                cover_url="/uploads/cover.jpg",
                duration="0:10",
                delay_ms=1500,
            )
        ]
    )
    html = render_template(cfg)
    assert 'video-bubble' in html
    assert "video-play" in html
    assert "0:10" in html
    assert "cover.jpg" in html


def test_emoji_message():
    """✅ emoji 消息渲染为大表情,不显示发送者名字。"""
    cfg = make_config(
        messages=[Message(sender_id="her", kind="emoji", text="🤔", delay_ms=1500)]
    )
    html = render_template(cfg)
    assert 'class="msg emoji' in html
    assert "🤔" in html
    assert 'emoji-text' in html


def test_consecutive_messages_hide_avatar():
    """✅ 同一发送者连续消息只显示一次头像。"""
    cfg = make_config(
        messages=[
            Message(sender_id="her", kind="text", text="第一条", delay_ms=1500),
            Message(sender_id="her", kind="text", text="第二条", delay_ms=1500),
        ]
    )
    html = render_template(cfg)
    # 第一条有头像,第二条通过 no-avatar 隐藏
    assert 'id="m1"' in html
    assert 'id="m2"' in html
    assert html.count('<div class="avatar avatar-default">') == 1
    # m2 应带 no-avatar 类
    assert _has_class(html, "div", "m2", "no-avatar")
