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


def test_single_mode_self_class():
    """✅ 单聊模式"自己"消息带 `.msg.self`。"""
    html = render_template(make_config())
    # m1 / m3 是我发的(右侧),m2 是她的(左侧)
    assert re.search(r'<div class="msg self" id="m1"', html)
    assert re.search(r'<div class="msg " id="m2"', html) or re.search(
        r'<div class="msg" id="m2"', html
    )
    assert re.search(r'<div class="msg self" id="m3"', html)


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
    assert 'class="sys-msg"' in html
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
    assert 'class="msg self" id="m1"' in html


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
    assert 'class="msg " id="m1"' in html or 'class="msg" id="m1"' in html


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
    assert 'class="msg self" id="m1"' in html  # me 在右侧
    assert 'class="msg " id="m2"' in html or 'class="msg" id="m2"' in html  # b 在左侧


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
