"""模板渲染测试 — 见 docs/04-template.md §4.10、docs/06-acceptance.md CODE-3。"""

from __future__ import annotations

import json
import re

import pytest
from pydantic import ValidationError

from app.dsl import ChatScene, VideoDSL, auto_duration
from app.models import Message, Participant, StatusBar
from app.renderer import (
    build_timeline,
    render_dsl,
    resolve_duration_ms,
    resolve_upload_url,
)
from app.storage import BASE_URL


def make_scene(**overrides) -> ChatScene:
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
    return ChatScene(**base)


def make_dsl(**overrides) -> VideoDSL:
    return VideoDSL(scene=make_scene(**overrides))


# ---- 4.10 模板测试 ----

def test_minimal_config_renders_valid_html():
    """✅ 最小配置(2 参与者 / 1 文本消息)能渲染出合法 HTML。"""
    dsl = make_dsl(
        messages=[Message(sender_id="her", kind="text", text="你好", delay_ms=1500)]
    )
    html = render_dsl(dsl)
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
    html = render_dsl(make_dsl())
    # m1 / m3 是我发的(右侧),m2 是她的(左侧)
    assert _has_class(html, "div", "m1", "self")
    assert _has_class(html, "div", "m2", "msg")
    assert _has_class(html, "div", "m3", "self")


def test_image_message_generates_img():
    """✅ 图片消息生成 `<img>` 标签,相对路径被补成绝对 URL。"""
    dsl = make_dsl(
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
    html = render_dsl(dsl)
    assert f'<img src="{BASE_URL}/uploads/plum.jpg"' in html
    assert "倚梅园的梅花开了。" in html


def test_sys_message_no_avatar_and_flash():
    """✅ 系统消息不显示头像;含"移出"时带 flash 红色脉冲。"""
    dsl = make_dsl(
        messages=[
            Message(
                sender_id="__system__", kind="sys", text="余答应已被移出群聊", delay_ms=1500
            )
        ]
    )
    html = render_dsl(dsl)
    assert re.search(r'class="sys-msg\b', html)
    assert 'class="avatar' not in html  # 系统消息无头像
    timeline = build_timeline(dsl.scene)
    assert timeline[-1]["type"] == "sys"
    assert timeline[-1]["flash"] is True
    assert "flash" in html  # CSS 里定义了 flash 动画


def test_timeline_json_parses():
    """✅ TIMELINE JSON 合法可被 JSON.parse 解析。"""
    dsl = make_dsl()
    html = render_dsl(dsl)
    m = re.search(r"const TIMELINE = (\[.*?\]);", html, re.S)
    assert m, "TIMELINE not found in rendered html"
    parsed = json.loads(m.group(1))
    assert parsed[0] == {"id": "m1", "at": 500, "type": "msg", "flash": False}
    ids = [t["id"] for t in parsed]
    assert ids == ["m1", "m2", "m3"]
    # 时间轴递增
    ats = [t["at"] for t in parsed]
    assert ats == sorted(ats)


def test_text_message_requires_text():
    """✅ 缺少 text 的 text 类消息报错(含纯空白)。"""
    for bad in (None, "", "   "):
        with pytest.raises(ValidationError):
            make_dsl(
                messages=[Message(sender_id="her", kind="text", text=bad, delay_ms=1500)]
            )


def test_missing_avatar_uses_default_placeholder():
    """✅ 缺头像 URL 的消息用默认占位图(灰色 div)。"""
    dsl = make_dsl(
        participants=[
            Participant(id="me", name="我", avatar_url=None),
            Participant(id="her", name="她", avatar_url=None),
        ]
    )
    html = render_dsl(dsl)
    assert 'class="avatar avatar-default"' in html


def test_avatar_url_inlined_when_present():
    """✅ 有头像 URL 时内联 background-image,并补成绝对 URL。"""
    dsl = make_dsl(
        participants=[
            Participant(id="me", name="我", avatar_url="/uploads/me.png"),
            Participant(id="her", name="她", avatar_url=None),
        ]
    )
    html = render_dsl(dsl)
    assert f"background-image: url('{BASE_URL}/uploads/me.png')" in html


def test_background_image_url_rendered():
    """✅ 设置 background_image_url 时内联整页背景图,并补成绝对 URL,保留颜色兜底。"""
    dsl = make_dsl(background_image_url="/uploads/bg.png")
    html = render_dsl(dsl)
    assert "background: #ededed" in html  # 颜色兜底仍在
    assert f"background-image: url('{BASE_URL}/uploads/bg.png')" in html
    assert "background-size: cover" in html
    assert "background-position: center" in html


def test_no_background_image_renders_plain_color():
    """✅ 未设置 background_image_url 时不输出背景图样式。"""
    html = render_dsl(make_dsl())
    assert "background: #ededed" in html
    assert "background-image: url(" not in html


# ---- 时长 / 方向规则 / 校验 ----

def test_auto_duration_formula():
    """PERF-1:5 条消息 delay=1500 → 500 + 5*1500 + 1500 = 9500。"""
    msgs = [
        Message(sender_id="me", kind="text", text="x", delay_ms=1500) for _ in range(5)
    ]
    assert auto_duration(msgs) == 9500
    dsl = make_dsl(messages=msgs)
    assert resolve_duration_ms(dsl.scene) == 9500


def test_explicit_duration_wins():
    """✅ 用户显式 duration_ms 覆盖自动时长。"""
    dsl = make_dsl(duration_ms=30000)
    assert resolve_duration_ms(dsl.scene) == 30000


def test_group_me_message_on_right():
    """✅ 群聊中 id=='me' 的参与者消息走右侧。"""
    dsl = VideoDSL(
        scene=ChatScene(
            mode="group",
            participants=[
                Participant(id="me", name="我"),
                Participant(id="bob", name="Bob"),
            ],
            messages=[Message(sender_id="me", kind="text", text="在吗", delay_ms=1500)],
        )
    )
    html = render_dsl(dsl)
    assert _has_class(html, "div", "m1", "self")


def test_group_other_message_on_left():
    """✅ 群聊中非 me 的消息走左侧白底。"""
    dsl = VideoDSL(
        scene=ChatScene(
            mode="group",
            participants=[
                Participant(id="me", name="我"),
                Participant(id="bob", name="Bob"),
            ],
            messages=[Message(sender_id="bob", kind="text", text="在吗", delay_ms=1500)],
        )
    )
    html = render_dsl(dsl)
    assert _has_class(html, "div", "m1", "msg")


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
    """✅ `__system__` 仅对 sys / timestamp 消息合法;其他类型会被后端拒绝,
    防止前端误把系统消息切换为文字/图片后仍带上 __system__ sender_id。
    """
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


def test_single_mode_accepts_three_participants():
    """✅ 单聊不限制恰好 2 人:participants[0] 为"我",其余走左侧(切换模式不破坏预览)。"""
    dsl = VideoDSL(
        scene=ChatScene(
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
    )
    html = render_dsl(dsl)
    assert _has_class(html, "div", "m1", "self")  # me 在右侧
    assert _has_class(html, "div", "m2", "msg")  # b 在左侧


def test_requires_at_least_two_participants():
    """✅ 参与者少于 2 个报错(与模式无关)。"""
    with pytest.raises(ValidationError):
        ChatScene(
            mode="single",
            participants=[Participant(id="a", name="A")],
            messages=[Message(sender_id="a", kind="text", text="x", delay_ms=1500)],
        )
    with pytest.raises(ValidationError):
        ChatScene(
            mode="group",
            participants=[Participant(id="a", name="A")],
            messages=[Message(sender_id="a", kind="text", text="x", delay_ms=1500)],
        )


# ---- 新增:状态栏 / 头部 / 视频 / 表情 / 时间戳 / 合并头像 ----

def test_status_bar_rendered():
    """✅ 状态栏时间、双卡、电池可配置（fluentui 图标內联）。"""
    dsl = make_dsl(
        status_bar=StatusBar(
            time="00:00",
            battery_level=61,
            signal_type="5G",
            dual_sim=True,
            show_wifi=True,
            show_signal=True,
            show_bluetooth=True,
            show_alarm=True,
        )
    )
    html = render_dsl(dsl)
    assert "00:00" in html
    assert "5G" in html
    # fluentui 电池图标已內联(SVG),Battery 6 对应 61% (path起点唯一)
    assert 'M17.0001 6C18.65' in html
    # 闹钟 / 蓝牙 / WiFi / 信号条形(主+副) / 电池 共 6 个 SVG
    assert html.count("<svg") >= 6


def test_single_subtitle_rendered():
    """✅ 单聊副标题显示在标题下方。"""
    dsl = make_dsl(mode="single", subtitle="云熙数码")
    html = render_dsl(dsl)
    assert 'class="subtitle"' in html
    assert "云熙数码" in html


def test_group_member_count_and_mute_bell():
    """✅ 群聊人数和免打扰铃铛显示在头部。"""
    dsl = VideoDSL(
        scene=ChatScene(
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
    )
    html = render_dsl(dsl)
    assert "(221)" in html
    assert 'class="mute-bell"' in html


def test_participant_label_rendered():
    """✅ 参与者 label 在群聊昵称旁显示。"""
    dsl = VideoDSL(
        scene=ChatScene(
            mode="group",
            participants=[
                Participant(id="me", name="我"),
                Participant(id="bob", name="Bob", label="【OPC圈成都】"),
            ],
            messages=[Message(sender_id="bob", kind="text", text="hi", delay_ms=1500)],
        )
    )
    html = render_dsl(dsl)
    assert "【OPC圈成都】" in html


def test_timestamp_message():
    """✅ timestamp 消息渲染为时间分隔线,不占用聊天头像。"""
    dsl = make_dsl(
        messages=[
            Message(sender_id="__system__", kind="timestamp", text="星期五 18:27", delay_ms=1500),
            Message(sender_id="her", kind="text", text="你好", delay_ms=1500),
        ]
    )
    html = render_dsl(dsl)
    assert 'class="time-stamp"' in html
    assert "星期五 18:27" in html
    # 时间戳消息 m1 本身不含头像
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
    """✅ emoji 消息渲染为大表情,不显示发送者名字。"""
    dsl = make_dsl(
        messages=[Message(sender_id="her", kind="emoji", text="🤔", delay_ms=1500)]
    )
    html = render_dsl(dsl)
    assert 'class="msg emoji' in html
    assert "🤔" in html
    assert 'emoji-text' in html


def test_resolve_upload_url_converts_relative_paths():
    """✅ 相对上传路径补成 BASE_URL,绝对 URL / data URL 保持不变。"""
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
    # 两条消息都应有头像
    assert 'id="m1"' in html
    assert 'id="m2"' in html
    assert html.count('<div class="avatar avatar-default">') == 2
    # m2 不应带 no-avatar 类
    assert not _has_class(html, "div", "m2", "no-avatar")
