"""模板渲染测试 — 见 docs/04-template.md §4.10、docs/06-acceptance.md CODE-3。"""

from __future__ import annotations

import json
import re

import pytest
from pydantic import ValidationError

from app.dsl import ChatScene, VideoDSL, auto_duration
from app.models import Message, Participant
from app.renderer import (
    build_timeline,
    render_dsl,
    resolve_duration_ms,
    resolve_upload_url,
)
from app.storage import BASE_URL


def make_scene(**overrides) -> ChatScene:
    participants = [
        Participant(id="me", name="我", avatar_url=None, persona=""),
        Participant(id="her", name="她", avatar_url=None, persona=""),
    ]
    messages = [
        Message(sender_id="me", kind="text", text="在吗", delay_ms=1500),
        Message(sender_id="her", kind="text", text="嗯", delay_ms=1500),
        Message(sender_id="me", kind="text", text="周末吃饭?", delay_ms=1500),
    ]
    base = dict(
        mode="single",
        participants=participants,
        messages=messages,
        intent="short_video_drama",
        intent_acknowledged=True,
    )
    base.update(overrides)
    return ChatScene(**base)


def make_dsl(template: str = "cyberpunk", **overrides) -> VideoDSL:
    return VideoDSL(template=template, scene=make_scene(**overrides))


# ---- 4.10 模板测试 ----

@pytest.mark.parametrize("template", ["cyberpunk", "watercolor", "pixel", "comic"])
def test_minimal_config_renders_valid_html(template):
    """✅ 最小配置（2 参与者 / 1 文本消息）在 4 种风格下都能渲染出合法 HTML。"""
    dsl = make_dsl(
        template=template,
        messages=[Message(sender_id="her", kind="text", text="你好", delay_ms=1500)],
    )
    html = render_dsl(dsl)
    assert html.strip().startswith("<!DOCTYPE html>")
    assert "<html" in html and "</html>" in html
    assert "<body" in html and "</body>" in html
    assert "你好" in html
    assert 'id="m1"' in html
    assert template in html.lower() or "dialogue theater" in html.lower()


def _has_class(html: str, tag: str, dom_id: str, klass: str) -> bool:
    """辅助：在 html 里查找 tag 且 id=dom_id 且 class 包含 klass 的元素。"""
    return bool(
        re.search(
            rf'<{tag}\s+class="[^"]*\b{re.escape(klass)}\b[^"]*"\s+id="{dom_id}"',
            html,
        )
    )


def test_single_mode_self_class():
    """✅ 单聊模式"自己"消息带 `.msg.self`。"""
    html = render_dsl(make_dsl())
    # m1 / m3 是我发的（右侧），m2 是她的（左侧）
    assert _has_class(html, "div", "m1", "self")
    assert _has_class(html, "div", "m2", "msg")
    assert _has_class(html, "div", "m3", "self")


def test_image_message_generates_img():
    """✅ 图片消息生成 `<img>` 标签，相对路径被补成绝对 URL。"""
    dsl = make_dsl(
        messages=[
            Message(
                sender_id="me",
                kind="image",
                image_url="/uploads/plum.jpg",
                text="霓虹下的梅花开了。",
                delay_ms=1500,
            )
        ]
    )
    html = render_dsl(dsl)
    assert f'<img src="{BASE_URL}/uploads/plum.jpg"' in html
    assert "霓虹下的梅花开了。" in html


def test_sys_message_no_avatar():
    """✅ 系统消息渲染为幕间字幕，不显示头像。"""
    dsl = make_dsl(
        messages=[
            Message(
                sender_id="__system__", kind="sys", text="第三章：雨夜", delay_ms=1500
            )
        ]
    )
    html = render_dsl(dsl)
    assert re.search(r'class="sys-msg\b', html)
    assert 'class="avatar' not in html  # 系统消息无头像
    timeline = build_timeline(dsl.scene)
    assert timeline[-1]["type"] == "sys"


def test_timeline_includes_disclaimer_card():
    """✅ TIMELINE 开头固定包含 1 秒 AI 声明卡。"""
    dsl = make_dsl()
    timeline = build_timeline(dsl.scene)
    assert timeline[0] == {"id": "__disclaimer__", "at": 0, "type": "disclaimer"}


def test_timeline_json_parses():
    """✅ TIMELINE JSON 合法可被 JSON.parse 解析。"""
    dsl = make_dsl()
    html = render_dsl(dsl)
    m = re.search(r"const TIMELINE = (\[.*?\]);", html, re.S)
    assert m, "TIMELINE not found in rendered html"
    parsed = json.loads(m.group(1))
    assert parsed[0] == {"id": "__disclaimer__", "at": 0, "type": "disclaimer"}
    ids = [t["id"] for t in parsed]
    assert ids == ["__disclaimer__", "m1", "m2", "m3"]
    # 时间轴递增
    ats = [t["at"] for t in parsed]
    assert ats == sorted(ats)


def test_text_message_requires_text():
    """✅ 缺少 text 的 text 类消息报错（含纯空白）。"""
    for bad in (None, "", "   "):
        with pytest.raises(ValidationError):
            make_dsl(
                messages=[Message(sender_id="her", kind="text", text=bad, delay_ms=1500)]
            )


def test_missing_avatar_uses_default_placeholder():
    """✅ 缺头像 URL 的消息用默认六边形占位。"""
    dsl = make_dsl(
        participants=[
            Participant(id="me", name="我", avatar_url=None, persona=""),
            Participant(id="her", name="她", avatar_url=None, persona=""),
        ]
    )
    html = render_dsl(dsl)
    assert 'class="avatar avatar-default"' in html


def test_avatar_url_inlined_when_present():
    """✅ 有头像 URL 时内联 background-image，并补成绝对 URL。"""
    dsl = make_dsl(
        participants=[
            Participant(id="me", name="我", avatar_url="/uploads/me.png", persona=""),
            Participant(id="her", name="她", avatar_url=None, persona=""),
        ]
    )
    html = render_dsl(dsl)
    assert f"background-image: url('{BASE_URL}/uploads/me.png')" in html


def test_background_image_url_rendered():
    """✅ 设置 background_image_url 时内联整页背景图，并补成绝对 URL。"""
    dsl = make_dsl(background_image_url="/uploads/bg.png")
    html = render_dsl(dsl)
    assert f"background-image: url('{BASE_URL}/uploads/bg.png')" in html
    assert "background-size: cover" in html
    assert "background-position: center" in html


# ---- 时长 / 方向规则 / 校验 ----

def test_auto_duration_formula():
    """PERF-1：5 条消息 delay=1500 → 1000 + 5*1500 + 1500 = 10000（含声明卡）。"""
    msgs = [
        Message(sender_id="me", kind="text", text="x", delay_ms=1500) for _ in range(5)
    ]
    assert auto_duration(msgs, first_delay_ms=1000) == 10000
    dsl = make_dsl(messages=msgs)
    assert resolve_duration_ms(dsl.scene) == 10000


def test_explicit_duration_wins():
    """✅ 用户显式 duration_ms 覆盖自动时长。"""
    dsl = make_dsl(duration_ms=30000)
    assert resolve_duration_ms(dsl.scene) == 30000


def test_group_me_message_on_right():
    """✅ 群聊中 id=='me' 的参与者消息走右侧。"""
    dsl = VideoDSL(
        scene=ChatScene(
            mode="group",
            intent="short_video_drama",
            intent_acknowledged=True,
            participants=[
                Participant(id="me", name="我", persona=""),
                Participant(id="bob", name="Bob", persona=""),
            ],
            messages=[Message(sender_id="me", kind="text", text="在吗", delay_ms=1500)],
        )
    )
    html = render_dsl(dsl)
    assert _has_class(html, "div", "m1", "self")


def test_group_other_message_on_left():
    """✅ 群聊中非 me 的消息走左侧。"""
    dsl = VideoDSL(
        scene=ChatScene(
            mode="group",
            intent="short_video_drama",
            intent_acknowledged=True,
            participants=[
                Participant(id="me", name="我", persona=""),
                Participant(id="bob", name="Bob", persona=""),
            ],
            messages=[Message(sender_id="bob", kind="text", text="在吗", delay_ms=1500)],
        )
    )
    html = render_dsl(dsl)
    assert _has_class(html, "div", "m1", "msg")


def test_explicit_align_left_forces_left():
    """✅ align='left' 时，即使是 me 也走左侧。"""
    dsl = VideoDSL(
        scene=ChatScene(
            mode="group",
            intent="short_video_drama",
            intent_acknowledged=True,
            participants=[
                Participant(id="me", name="我", persona=""),
                Participant(id="bob", name="Bob", persona=""),
            ],
            messages=[Message(sender_id="me", kind="text", text="在吗", delay_ms=1500, align="left")],
        )
    )
    html = render_dsl(dsl)
    assert _has_class(html, "div", "m1", "msg")
    assert not _has_class(html, "div", "m1", "self")


def test_explicit_align_right_forces_right():
    """✅ align='right' 时，即使非 me 也走右侧。"""
    dsl = VideoDSL(
        scene=ChatScene(
            mode="group",
            intent="short_video_drama",
            intent_acknowledged=True,
            participants=[
                Participant(id="me", name="我", persona=""),
                Participant(id="bob", name="Bob", persona=""),
            ],
            messages=[Message(sender_id="bob", kind="text", text="在吗", delay_ms=1500, align="right")],
        )
    )
    html = render_dsl(dsl)
    assert _has_class(html, "div", "m1", "self")


def test_first_message_delay_minimum():
    """✅ 第一条消息 delay_ms < 500 报错。"""
    with pytest.raises(ValidationError):
        make_dsl(
            messages=[
                Message(sender_id="me", kind="text", text="在吗", delay_ms=300)
            ]
        )


def test_unknown_sender_rejected():
    """✅ sender_id 必须匹配某个参与者。"""
    with pytest.raises(ValidationError):
        make_dsl(
            messages=[
                Message(sender_id="zzz", kind="text", text="在吗", delay_ms=1500)
            ]
        )


def test_system_sender_id_only_valid_for_sys_or_timestamp():
    """✅ `__system__` 仅对 sys / timestamp 消息合法。"""
    # sys / timestamp:允许
    for kind in ("sys", "timestamp"):
        make_dsl(
            messages=[
                Message(
                    sender_id="__system__",
                    kind=kind,
                    text="hello",
                    delay_ms=1500,
                )
            ]
        )
    # text / image / video / emoji:必须拒绝
    for kind in ("text", "image", "video", "emoji"):
        payload = dict(sender_id="__system__", kind=kind, delay_ms=1500)
        if kind == "text":
            payload["text"] = "hello"
        elif kind == "image":
            payload["image_url"] = "/uploads/x.png"
        elif kind == "video":
            payload["video_url"] = "/uploads/v.mp4"
            payload["duration"] = "0:10"
        else:  # emoji
            payload["text"] = "🤔"
        with pytest.raises(ValidationError):
            make_dsl(messages=[Message(**payload)])


def test_negative_duration_rejected():
    """PERF-3:duration_ms=-1 → 422。"""
    with pytest.raises(ValidationError):
        make_dsl(duration_ms=-1)


def test_single_mode_requires_exactly_two_participants():
    """✅ 对谈模式限制为恰好 2 名角色。"""
    with pytest.raises(ValidationError):
        VideoDSL(
            scene=ChatScene(
                mode="single",
                intent="short_video_drama",
                intent_acknowledged=True,
                participants=[
                    Participant(id="me", name="我", persona=""),
                    Participant(id="a", name="A", persona=""),
                    Participant(id="b", name="B", persona=""),
                ],
                messages=[
                    Message(sender_id="me", kind="text", text="在吗", delay_ms=1500),
                    Message(sender_id="b", kind="text", text="你好", delay_ms=1500),
                ],
            )
        )


def test_group_mode_allows_more_than_two_participants():
    """✅ 群像模式允许 2 名以上角色。"""
    dsl = VideoDSL(
        scene=ChatScene(
            mode="group",
            intent="short_video_drama",
            intent_acknowledged=True,
            participants=[
                Participant(id="me", name="我", persona=""),
                Participant(id="a", name="A", persona=""),
                Participant(id="b", name="B", persona=""),
            ],
            messages=[
                Message(sender_id="me", kind="text", text="在吗", delay_ms=1500),
                Message(sender_id="b", kind="text", text="你好", delay_ms=1500),
            ],
        )
    )
    html = render_dsl(dsl)
    assert _has_class(html, "div", "m1", "self")  # me 在右侧
    assert _has_class(html, "div", "m2", "msg")  # b 在左侧


def test_requires_at_least_two_participants():
    """✅ 参与者少于 2 个报错（与模式无关）。"""
    with pytest.raises(ValidationError):
        ChatScene(
            mode="single",
            intent="short_video_drama",
            intent_acknowledged=True,
            participants=[Participant(id="a", name="A", persona="")],
            messages=[Message(sender_id="a", kind="text", text="x", delay_ms=1500)],
        )
    with pytest.raises(ValidationError):
        ChatScene(
            mode="group",
            intent="short_video_drama",
            intent_acknowledged=True,
            participants=[Participant(id="a", name="A", persona="")],
            messages=[Message(sender_id="a", kind="text", text="x", delay_ms=1500)],
        )


# ---- 消息类型 / 水印 / 合规 ----

def test_timestamp_message():
    """✅ timestamp 消息渲染为霓虹日期戳，不占用聊天头像。"""
    dsl = make_dsl(
        messages=[
            Message(sender_id="__system__", kind="timestamp", text="星期五 18:27", delay_ms=1500),
            Message(sender_id="her", kind="text", text="你好", delay_ms=1500),
        ]
    )
    html = render_dsl(dsl)
    assert 'class="time-stamp"' in html
    assert "星期五 18:27" in html
    m1_match = re.search(r'<div class="time-stamp" id="m1"[^>]*>.*?</div>', html, re.S)
    assert m1_match
    assert 'class="avatar' not in m1_match.group(0)


def test_video_message():
    """✅ video 消息渲染带播放按钮和时长。"""
    dsl = make_dsl(
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
    html = render_dsl(dsl)
    assert 'video-bubble' in html
    assert "video-play" in html
    assert "0:10" in html
    assert "cover.jpg" in html


def test_emoji_message():
    """✅ emoji 消息渲染为大表情，不显示发送者名字。"""
    dsl = make_dsl(
        messages=[Message(sender_id="her", kind="emoji", text="🤔", delay_ms=1500)]
    )
    html = render_dsl(dsl)
    assert 'class="msg emoji' in html
    assert "🤔" in html
    assert 'emoji-text' in html


def test_resolve_upload_url_converts_relative_paths():
    """✅ 相对上传路径补成 BASE_URL，绝对 URL / data URL 保持不变。"""
    assert resolve_upload_url("/uploads/x.png") == f"{BASE_URL}/uploads/x.png"
    assert resolve_upload_url("uploads/x.png") == f"{BASE_URL}/uploads/x.png"
    assert resolve_upload_url("https://example.com/a.png") == "https://example.com/a.png"
    assert resolve_upload_url("data:image/png;base64,abc") == "data:image/png;base64,abc"
    assert resolve_upload_url(None) is None
    assert resolve_upload_url("") == ""


def test_consecutive_messages_show_avatar():
    """✅ 同一发送者连续消息也显示头像。"""
    dsl = make_dsl(
        messages=[
            Message(sender_id="her", kind="text", text="第一条", delay_ms=1500),
            Message(sender_id="her", kind="text", text="第二条", delay_ms=1500),
        ]
    )
    html = render_dsl(dsl)
    assert 'id="m1"' in html
    assert 'id="m2"' in html
    assert html.count('<div class="avatar avatar-default">') == 2


# ---- 水印 / AI 标识 ----

def test_ai_badge_always_rendered():
    """✅ AI 生成角标始终渲染，不可关闭。"""
    dsl = make_dsl()
    html = render_dsl(dsl)
    assert 'class="ai-badge' in html
    assert "AI" in html or "生成" in html


def test_disclaimer_card_always_rendered():
    """✅ 片头声明卡始终渲染。"""
    dsl = make_dsl()
    html = render_dsl(dsl)
    assert 'id="__disclaimer__"' in html
    assert "本对话由 AI 生成" in html


# ---- 合规校验 ----

def test_missing_intent_rejected():
    """✅ 未选择创作意图时拒绝。"""
    with pytest.raises(ValidationError):
        make_dsl(intent="")


def test_unacknowledged_intent_rejected():
    """✅ 未勾选合规承诺时拒绝。"""
    with pytest.raises(ValidationError):
        make_dsl(intent_acknowledged=False)


def test_high_risk_word_rejected():
    """✅ 消息中出现高敏感词时拒绝。"""
    with pytest.raises(ValidationError):
        make_dsl(
            messages=[Message(sender_id="me", kind="text", text="请转账给我", delay_ms=1500)]
        )


def test_platform_name_rejected():
    """✅ 消息中出现真实社交平台名时拒绝。"""
    with pytest.raises(ValidationError):
        make_dsl(
            messages=[Message(sender_id="me", kind="text", text="这个微信截图", delay_ms=1500)]
        )


# ---- noir 主题测试 ----


def make_noir_dsl(**overrides) -> VideoDSL:
    return VideoDSL(template="noir", scene=make_scene(style_theme="noir", **overrides))


def test_noir_minimal_config_renders_valid_html():
    """✅ noir 最小配置渲染出合法 HTML。"""
    dsl = make_noir_dsl(
        messages=[Message(sender_id="her", kind="text", text="你好", delay_ms=1500)],
    )
    html = render_dsl(dsl)
    assert html.strip().startswith("<!DOCTYPE html>")
    assert "<html" in html and "</html>" in html
    assert "<body" in html and "</body>" in html
    assert "你好" in html
    assert 'id="m1"' in html
    assert "<title>Dialogue Theater — Noir</title>" in html


def test_noir_self_message():
    """✅ noir 单聊模式自己消息带 .msg.self。"""
    html = render_dsl(make_noir_dsl())
    assert _has_class(html, "div", "m1", "self")
    assert _has_class(html, "div", "m2", "msg")
    assert _has_class(html, "div", "m3", "self")


def test_noir_image_message():
    """✅ noir 图片消息生成 img 并强制灰阶。"""
    dsl = make_noir_dsl(
        messages=[
            Message(
                sender_id="me",
                kind="image",
                image_url="/uploads/plum.jpg",
                text="霓虹下的梅花开了。",
                delay_ms=1500,
            )
        ]
    )
    html = render_dsl(dsl)
    assert f'<img src="{BASE_URL}/uploads/plum.jpg"' in html
    assert "霓虹下的梅花开了。" in html
    assert "grayscale(1)" in html


def test_noir_video_message():
    """✅ noir 视频消息渲染播放按钮和时长。"""
    dsl = make_noir_dsl(
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
    html = render_dsl(dsl)
    assert "video-bubble" in html
    assert "video-play" in html
    assert "0:10" in html
    assert "cover.jpg" in html


def test_noir_emoji_message():
    """✅ noir emoji 消息渲染为大表情并强制灰阶。"""
    dsl = make_noir_dsl(
        messages=[Message(sender_id="her", kind="emoji", text="🤔", delay_ms=1500)]
    )
    html = render_dsl(dsl)
    assert 'class="msg emoji' in html
    assert "🤔" in html
    assert 'emoji-text' in html
    assert "grayscale(1)" in html


def test_noir_timestamp_message():
    """✅ noir 时间戳渲染为 .time-stamp。"""
    dsl = make_noir_dsl(
        messages=[
            Message(sender_id="__system__", kind="timestamp", text="12:47 AM", delay_ms=1500),
            Message(sender_id="her", kind="text", text="你好", delay_ms=1500),
        ]
    )
    html = render_dsl(dsl)
    assert 'class="time-stamp"' in html
    assert "12:47 AM" in html
    m1_match = re.search(r'<div class="time-stamp" id="m1"[^>]*>.*?</div>', html, re.S)
    assert m1_match
    assert 'class="avatar' not in m1_match.group(0)


def test_noir_sys_message():
    """✅ noir 系统消息渲染为幕间字幕，显示 REEL 序号，无头像。"""
    dsl = make_noir_dsl(
        messages=[
            Message(sender_id="__system__", kind="sys", text="ACT II · NIGHT", delay_ms=1500)
        ]
    )
    html = render_dsl(dsl)
    assert re.search(r'class="sys-msg\b', html)
    assert "REEL 01" in html
    assert "ACT II · NIGHT" in html
    assert 'class="avatar' not in html


def test_noir_timeline_includes_disclaimer_card():
    """✅ noir TIMELINE 开头固定包含 1 秒 AI 声明卡。"""
    dsl = make_noir_dsl()
    timeline = build_timeline(dsl.scene)
    assert timeline[0] == {"id": "__disclaimer__", "at": 0, "type": "disclaimer"}


def test_noir_consecutive_messages_show_avatar():
    """✅ noir 同一发送者连续消息也显示头像。"""
    dsl = make_noir_dsl(
        messages=[
            Message(sender_id="her", kind="text", text="第一条", delay_ms=1500),
            Message(sender_id="her", kind="text", text="第二条", delay_ms=1500),
        ]
    )
    html = render_dsl(dsl)
    assert 'id="m1"' in html
    assert 'id="m2"' in html
    assert html.count('<div class="avatar avatar-default">') == 2


def test_noir_missing_avatar_uses_default_placeholder():
    """✅ noir 缺头像 URL 用圆角正方形占位。"""
    dsl = make_noir_dsl(
        participants=[
            Participant(id="me", name="我", avatar_url=None, persona=""),
            Participant(id="her", name="她", avatar_url=None, persona=""),
        ]
    )
    html = render_dsl(dsl)
    assert 'class="avatar avatar-default"' in html


def test_noir_ai_badge_rendered():
    """✅ noir AI 角标始终渲染。"""
    dsl = make_noir_dsl()
    html = render_dsl(dsl)
    assert 'class="ai-badge' in html
    assert "AI" in html or "生成" in html


def test_noir_reply_quote_renders():
    """✅ noir 带 reply_to 的消息渲染 .reply-quote。"""
    dsl = make_noir_dsl(
        messages=[
            Message(sender_id="her", kind="text", text="原始消息内容", delay_ms=1500),
            Message(sender_id="me", kind="text", text="这是回复", delay_ms=1500, reply_to=1),
        ]
    )
    html = render_dsl(dsl)
    assert 'class="reply-quote"' in html
    assert "原始消息内容" in html
    assert "她" in html
    assert "data-reply-to=\"m1\"" in html


def test_noir_no_colorful_hex():
    """✅ noir 模板产物只含灰阶（允许设计文档中明确的象牙白纸色 #f5f0e1）。"""
    # 使用中性灰背景，避免用户传入的背景色干扰判断
    background = "#c7c7c7"
    dsl = make_noir_dsl(
        background=background,
        messages=[
            Message(sender_id="her", kind="text", text="你好", delay_ms=1500),
            Message(sender_id="me", kind="emoji", text="🎭", delay_ms=1500),
            Message(sender_id="__system__", kind="sys", text="ACT I", delay_ms=1500),
        ],
    )
    html = render_dsl(dsl)
    html_for_check = html.replace(background, "")
    # 允许设计文档中明确使用的象牙白纸色 #f5f0e1（严格来说不是纯灰阶）
    allowed_non_grayscale = {"#f5f0e1"}
    for match in re.finditer(r"#([0-9a-fA-F]{3}){1,2}\b", html_for_check):
        color = match.group(0).lower()
        if color in allowed_non_grayscale:
            continue
        hex_val = color.lstrip("#")
        if len(hex_val) == 3:
            r, g, b = hex_val[0] * 2, hex_val[1] * 2, hex_val[2] * 2
        else:
            r, g, b = hex_val[0:2], hex_val[2:4], hex_val[4:6]
        assert r == g == b, f"noir theme contains non-grayscale color: {color}"
