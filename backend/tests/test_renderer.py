"""模板渲染测试 — 见 docs/04-template.md §4.10、docs/06-acceptance.md CODE-3。"""

from __future__ import annotations

import json
import re

import pytest
from pydantic import ValidationError

from app.dsl import ChatScene, VideoDSL, auto_duration
from app.models import Message, Participant
from app.renderer import (
    INTRO_DURATION_MS,
    TYPEWRITER_INITIAL_MS,
    TYPEWRITER_PER_CHAR_MS,
    TYPEWRITER_FADE_MS,
    build_timeline,
    build_timeline_with_durations,
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


def test_timeline_includes_intro_effect_when_enabled():
    """✅ 启用 intro_effect 时 TIMELINE 包含 __intro__ 节点并顺延后续消息。"""
    dsl = make_dsl(intro_effect="scanline")
    timeline = build_timeline(dsl.scene)
    assert timeline[0] == {"id": "__disclaimer__", "at": 0, "type": "disclaimer"}
    assert timeline[1] == {"id": "__intro__", "at": 1000, "type": "intro", "effect": "scanline"}
    # 第一条消息应在声明卡 1s + intro 之后
    assert timeline[2]["at"] == 1000 + INTRO_DURATION_MS


def test_timeline_no_intro_effect_when_disabled():
    """✅ 关闭 intro_effect 时 TIMELINE 不包含 __intro__。"""
    dsl = make_dsl(intro_effect="none")
    timeline = build_timeline(dsl.scene)
    ids = [t["id"] for t in timeline]
    assert "__intro__" not in ids
    assert timeline[1]["at"] == 1000


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


def test_auto_duration_includes_intro_effect():
    """✅ 自动算时长把 intro_effect 的时间计入。"""
    msgs = [
        Message(sender_id="me", kind="text", text="x", delay_ms=1500) for _ in range(5)
    ]
    dsl = make_dsl(messages=msgs, intro_effect="scanline")
    expected = 1000 + INTRO_DURATION_MS + 5 * 1500 + 1500
    assert resolve_duration_ms(dsl.scene) == expected


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


@pytest.mark.parametrize("template", ["cyberpunk", "watercolor", "pixel", "comic", "noir", "ink"])
@pytest.mark.parametrize("effect", ["scanline", "typewriter"])
def test_intro_effect_overlay_rendered(template, effect):
    """✅ 6 种风格在启用特效时渲染对应的 #intro-overlay 子元素。"""
    dsl = make_dsl(template=template, intro_effect=effect)
    html = render_dsl(dsl)
    assert 'id="__intro__"' in html
    assert f'intro-{effect}' in html
    if effect == "scanline":
        assert 'class="intro-line"' in html
        assert 'class="intro-mask"' in html
    elif effect == "typewriter":
        assert 'id="theater-title"' in html
        assert 'class="intro-typewriter"' in html


def test_intro_effect_none_does_not_render_overlay():
    """✅ 关闭特效时不渲染 #intro-overlay。"""
    dsl = make_dsl(intro_effect="none")
    html = render_dsl(dsl)
    assert 'id="__intro__"' not in html


@pytest.mark.parametrize("effect", ["none", "scanline", "typewriter"])
def test_title_always_rendered_in_header(effect):
    """✅ 三种开头特效都把 #theater-title 渲染到 header 里;
    none/scanline 直接渲染文本;typewriter 模式 #theater-title 初始为空,
    由 JS typewriteTitle 把 TYPEWRITER_TITLE 逐字写入(玩家透过半透明 overlay 看到打字过程),
    完成后保留。"""
    import json

    dsl = make_dsl(intro_effect=effect)
    html = render_dsl(dsl)
    assert 'id="theater-title"' in html
    if effect == "typewriter":
        # typewriter 模式:div 初始为空,文本以 const TYPEWRITER_TITLE = {{ title | tojson }} 形式交给 JS
        assert 'id="theater-title"></div>' in html
        assert "TYPEWRITER_TITLE" in html
        # tojson 默认对非 ASCII 转义,断言其 unicode-escape 形式在 HTML 中
        assert json.dumps("对话剧场", ensure_ascii=True) in html
    else:
        # 其他模式:文本直接渲染到 div
        assert 'id="theater-title">对话剧场</div>' in html


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


def test_platform_name_not_matched_as_substring():
    """✅ 英文平台名按单词边界匹配,避免 "Meta" 误杀 "Metal" 等词汇。"""
    dsl = make_dsl(
        messages=[Message(sender_id="me", kind="text", text="Metal 是苹果图形 API", delay_ms=1500)]
    )
    assert dsl.scene.messages[0].text == "Metal 是苹果图形 API"


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


# ---- ink 主题测试 ----


INK_ALLOWED_COLORS = {
    "#f4ecd8",
    "#fcfaf2",
    "#1a1a1a",
    "#4a4a4a",
    "#8a8578",
    "#b8332b",
    "#8a2520",
    "#ffffff",
    # 3 位简写
    "#fff",
    "#000",
}


def make_ink_dsl(**overrides) -> VideoDSL:
    return VideoDSL(template="ink", scene=make_scene(style_theme="ink", **overrides))


def test_ink_minimal_config_renders_valid_html():
    """✅ ink 最小配置渲染出合法 HTML。"""
    dsl = make_ink_dsl(
        messages=[Message(sender_id="her", kind="text", text="你好", delay_ms=1500)],
    )
    html = render_dsl(dsl)
    assert html.strip().startswith("<!DOCTYPE html>")
    assert "<html" in html and "</html>" in html
    assert "<body" in html and "</body>" in html
    assert "你好" in html
    assert 'id="m1"' in html
    assert "<title>Dialogue Theater — Ink</title>" in html


def test_ink_self_message():
    """✅ ink 单聊模式自己消息带 .msg.self。"""
    html = render_dsl(make_ink_dsl())
    assert _has_class(html, "div", "m1", "self")
    assert _has_class(html, "div", "m2", "msg")
    assert _has_class(html, "div", "m3", "self")


def test_ink_image_message():
    """✅ ink 图片消息生成 img 并带 sepia 滤镜。"""
    dsl = make_ink_dsl(
        messages=[
            Message(
                sender_id="me",
                kind="image",
                image_url="/uploads/plum.jpg",
                text="梅花开了。",
                delay_ms=1500,
            )
        ]
    )
    html = render_dsl(dsl)
    assert f'<img src="{BASE_URL}/uploads/plum.jpg"' in html
    assert "梅花开了。" in html
    assert "sepia(0.25)" in html


def test_ink_video_message():
    """✅ ink 视频消息渲染播放按钮和时长。"""
    dsl = make_ink_dsl(
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


def test_ink_emoji_message():
    """✅ ink emoji 消息渲染为大表情并保留颜色。"""
    dsl = make_ink_dsl(
        messages=[Message(sender_id="her", kind="emoji", text="🤔", delay_ms=1500)]
    )
    html = render_dsl(dsl)
    assert 'class="msg emoji' in html
    assert "🤔" in html
    assert 'emoji-text' in html
    assert "drop-shadow(2px 2px 0" in html


def test_ink_timestamp_message():
    """✅ ink 时间戳渲染为 .time-stamp。"""
    dsl = make_ink_dsl(
        messages=[
            Message(sender_id="__system__", kind="timestamp", text="星期日 · 14:30", delay_ms=1500),
            Message(sender_id="her", kind="text", text="你好", delay_ms=1500),
        ]
    )
    html = render_dsl(dsl)
    assert 'class="time-stamp"' in html
    assert "星期日 · 14:30" in html
    m1_match = re.search(r'<div class="time-stamp" id="m1"[^>]*>.*?</div>', html, re.S)
    assert m1_match
    assert 'class="avatar' not in m1_match.group(0)


def test_ink_sys_message():
    """✅ ink 系统消息渲染为朱红方印，无头像。"""
    dsl = make_ink_dsl(
        messages=[
            Message(sender_id="__system__", kind="sys", text="风起云隐", delay_ms=1500)
        ]
    )
    html = render_dsl(dsl)
    assert 'class="sys-seal"' in html
    assert "风" in html  # 首字印章
    assert 'class="avatar' not in html


def test_ink_sys_seal_uses_first_char():
    """✅ ink 系统消息印章优先使用 sys.text 首字，非 CJK 回退"印"。"""
    dsl_cjk = make_ink_dsl(
        messages=[Message(sender_id="__system__", kind="sys", text="云涌", delay_ms=1500)]
    )
    html_cjk = render_dsl(dsl_cjk)
    seal_cjk = re.search(
        r'<div class="sys-seal"[^>]*>.*?<span class="sys-seal-char">(.*?)</span>',
        html_cjk,
        re.S,
    )
    assert seal_cjk and seal_cjk.group(1).strip() == "云"

    dsl_en = make_ink_dsl(
        messages=[Message(sender_id="__system__", kind="sys", text="ACT I", delay_ms=1500)]
    )
    html_en = render_dsl(dsl_en)
    seal_en = re.search(
        r'<div class="sys-seal"[^>]*>.*?<span class="sys-seal-char">(.*?)</span>',
        html_en,
        re.S,
    )
    assert seal_en and seal_en.group(1).strip() == "印"


def test_ink_timeline_includes_disclaimer_card():
    """✅ ink TIMELINE 开头固定包含 1 秒 AI 声明卡。"""
    dsl = make_ink_dsl()
    timeline = build_timeline(dsl.scene)
    assert timeline[0] == {"id": "__disclaimer__", "at": 0, "type": "disclaimer"}


def test_ink_consecutive_messages_show_avatar():
    """✅ ink 同一发送者连续消息也显示头像。"""
    dsl = make_ink_dsl(
        messages=[
            Message(sender_id="her", kind="text", text="第一条", delay_ms=1500),
            Message(sender_id="her", kind="text", text="第二条", delay_ms=1500),
        ]
    )
    html = render_dsl(dsl)
    assert 'id="m1"' in html
    assert 'id="m2"' in html
    assert html.count('<div class="avatar avatar-default"') == 2


def test_ink_missing_avatar_uses_default_placeholder():
    """✅ ink 缺头像 URL 用圆形朱印占位。"""
    dsl = make_ink_dsl(
        participants=[
            Participant(id="me", name="我", avatar_url=None, persona=""),
            Participant(id="her", name="她", avatar_url=None, persona=""),
        ]
    )
    html = render_dsl(dsl)
    assert 'class="avatar avatar-default"' in html


def test_ink_ai_badge_rendered():
    """✅ ink AI 角标始终渲染。"""
    dsl = make_ink_dsl()
    html = render_dsl(dsl)
    assert 'class="ai-badge' in html
    assert "AI" in html or "生成" in html


def test_ink_reply_quote_renders():
    """✅ ink 带 reply_to 的消息渲染 .reply-quote。"""
    dsl = make_ink_dsl(
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


def test_ink_avatar_rotation():
    """✅ ink 头像 inline style 包含 rotate 且角度在 [-3, +3] 范围内。"""
    dsl = make_ink_dsl()
    html = render_dsl(dsl)
    # 仅匹配 .avatar 元素上的 transform: rotate(...)（避免标题/系统印章的 -5° 被误扫）
    rotations = re.findall(
        r'<div class="avatar[^"]*"[^>]*style="[^"]*transform:\s*rotate\(([-\d.]+)deg\)',
        html,
    )
    assert rotations, "no avatar rotation found"
    for deg_str in rotations:
        deg = float(deg_str)
        assert -3 <= deg <= 3, f"avatar rotation {deg} out of [-3, +3] range"


def test_ink_svg_filter_and_displacement_map():
    """✅ ink 模板包含 SVG 笔触滤镜与 feDisplacementMap。"""
    dsl = make_ink_dsl(messages=[Message(sender_id="her", kind="text", text="你好", delay_ms=1500)])
    html = render_dsl(dsl)
    assert '<filter id="ink-edge"' in html
    assert "feDisplacementMap" in html


def test_ink_color_whitelist():
    """✅ ink 模板产物只使用设计文档中允许的配色。"""
    # 用一个不在 ink 调色板里的背景色渲染，渲染后移除它再扫描
    background = "#c7c7c7"
    dsl = make_ink_dsl(
        background=background,
        messages=[
            Message(sender_id="her", kind="text", text="你好", delay_ms=1500),
            Message(sender_id="me", kind="emoji", text="🗡️", delay_ms=1500),
            Message(sender_id="__system__", kind="sys", text="云涌", delay_ms=1500),
        ],
    )
    html = render_dsl(dsl)
    html_for_check = html.replace(background, "")
    for match in re.finditer(r"#([0-9a-fA-F]{3}){1,2}\b", html_for_check):
        color = match.group(0).lower()
        assert color in INK_ALLOWED_COLORS, f"ink theme contains unexpected color: {color}"


# ---- build_timeline_with_durations(新,与 build_timeline 并列) ----

def test_build_timeline_with_durations_basic():
    """✅ 3 条消息 + intro=none → 5 条事件(disclaimer + 3 条消息 + ?)。
    每条事件都有 appeared_at / disappeared_at / duration_ms,相邻事件 disappeared == 下一条 at,
    最后一条 disappeared == total_duration_ms。
    """
    dsl = make_dsl(intro_effect="none")
    total_ms = resolve_duration_ms(dsl.scene)
    entries = build_timeline_with_durations(dsl.scene, total_duration_ms=total_ms)
    # disclaimer + 3 msg
    assert len(entries) == 4
    assert [e["id"] for e in entries] == ["__disclaimer__", "m1", "m2", "m3"]

    # appeared_at 与 build_timeline 对齐
    timeline = build_timeline(dsl.scene)
    for e, t in zip(entries, timeline):
        assert e["at"] == t["at"]
        assert e["appeared_at"] == t["at"]

    # 消失语义:上一条 disappeared = 下一条 at;末条 = total_ms
    assert entries[0]["disappeared_at"] == entries[1]["at"]  # disclaimer 让位给 m1
    assert entries[1]["disappeared_at"] == entries[2]["at"]
    assert entries[2]["disappeared_at"] == entries[3]["at"]
    assert entries[3]["disappeared_at"] == total_ms

    # duration_ms 永远 ≥ 0
    for e in entries:
        assert e["duration_ms"] == e["disappeared_at"] - e["appeared_at"]
        assert e["duration_ms"] >= 0


def test_build_timeline_with_durations_includes_intro():
    """✅ intro_effect=scanline 时多一条 __intro__,intro 在声明卡之后、首条消息之前。"""
    dsl = make_dsl(intro_effect="scanline")
    entries = build_timeline_with_durations(dsl.scene)
    assert [e["id"] for e in entries[:2]] == ["__disclaimer__", "__intro__"]
    # intro 出现于 1000,消失于 1000 + INTRO_DURATION_MS
    intro = entries[1]
    assert intro["appeared_at"] == 1000
    assert intro["disappeared_at"] == 1000 + INTRO_DURATION_MS
    assert intro["type"] == "intro"
    assert intro["kind"] == "intro"
    # 条 3 是 m1,出现于 intro 结束时刻
    assert entries[2]["appeared_at"] == 1000 + INTRO_DURATION_MS


def test_build_timeline_with_durations_typewriter_intro_uses_title_length():
    """✅ typewriter 模式下 intro_duration 取决于标题字符数,intro 区间应包含整段打字+淡出。"""
    title = "很长的标题用于测试打字机效果"  # 14 个字符
    expected_intro = (
        TYPEWRITER_INITIAL_MS
        + len(title) * TYPEWRITER_PER_CHAR_MS
        + TYPEWRITER_FADE_MS
    )
    dsl = make_dsl(intro_effect="typewriter", title=title)
    entries = build_timeline_with_durations(dsl.scene)
    intro = next(e for e in entries if e["id"] == "__intro__")
    assert intro["disappeared_at"] - intro["appeared_at"] == expected_intro


def test_build_timeline_with_durations_first_timestamp_message():
    """✅ 首条 timestamp 消息额外加 700ms 间隔,然后才轮到第二条消息出现。"""
    dsl = make_dsl(
        messages=[
            Message(sender_id="__system__", kind="timestamp", text="19:00", delay_ms=1500),
            Message(sender_id="her", kind="text", text="hi", delay_ms=1500),
        ],
    )
    entries = build_timeline_with_durations(dsl.scene)
    ids = [e["id"] for e in entries]
    assert ids == ["__disclaimer__", "m1", "m2"]
    # m1 (timestamp) 出现于 1000(无 intro),700ms 后 m2 出现
    assert entries[1]["appeared_at"] == 1000
    assert entries[2]["appeared_at"] == 1000 + 700
    assert entries[1]["kind"] == "timestamp"
    # 类型映射为 timeline 用的 type 字段
    assert entries[1]["type"] == "timestamp"


def test_build_timeline_with_durations_explicit_total_duration():
    """✅ 用户显式传 total_duration_ms 时,末条 disappeared_at 与之一致。"""
    dsl = make_dsl(intro_effect="none")
    entries = build_timeline_with_durations(dsl.scene, total_duration_ms=30000)
    assert entries[-1]["disappeared_at"] == 30000


def test_build_timeline_with_durations_summaries():
    """✅ summary 字段给前端表格用:文字取首行 / 图片 / 视频 / emoji / sys / timestamp 各有格式。"""
    msgs = [
        Message(sender_id="her", kind="text", text="第一行\n第二行", delay_ms=1500),
        Message(sender_id="me", kind="image", image_url="/u/x.png", text="樱花", delay_ms=1500),
        Message(sender_id="me", kind="video", video_url="/u/v.mp4", duration="0:10", delay_ms=1500),
        Message(sender_id="her", kind="emoji", text="🤔", delay_ms=1500),
        Message(sender_id="__system__", kind="sys", text="第三章", delay_ms=1500),
        Message(sender_id="__system__", kind="timestamp", text="12:00", delay_ms=1500),
    ]
    dsl = make_dsl(messages=msgs, intro_effect="none")
    entries = build_timeline_with_durations(dsl.scene)
    # 跳过 disclaimer
    by_kind = {e["kind"]: e for e in entries if e["kind"] != "disclaimer"}
    assert by_kind["text"]["summary"] == "第一行"
    assert by_kind["image"]["summary"] == "[图片] 樱花"
    assert by_kind["video"]["summary"] == "[视频]"  # video 没 text,strip 后不带尾随空格
    assert by_kind["emoji"]["summary"] == "🤔"
    assert by_kind["sys"]["summary"] == "第三章"
    assert by_kind["timestamp"]["summary"] == "12:00"


def test_build_timeline_with_durations_sender_metadata_for_msg():
    """✅ 普通 / 时间戳消息带 sender_id,sys / timestamp 始终是 __system__。"""
    dsl = make_dsl(intro_effect="none")
    entries = build_timeline_with_durations(dsl.scene)
    # m1 是 me 发的,m2 是 her
    assert entries[1]["sender_id"] == "me"
    assert entries[1]["sender_name"] == "我"
    assert entries[2]["sender_id"] == "her"
    assert entries[2]["sender_name"] == "她"


def test_build_timeline_with_durations_message_image_url_inlined():
    """✅ message 的 image_url / video_url 字段被透传(相对路径补成绝对 URL 来自 build_messages)。"""
    dsl = make_dsl(
        messages=[
            Message(
                sender_id="her",
                kind="image",
                image_url="/uploads/x.png",
                text="x",
                delay_ms=1500,
            ),
        ],
    )
    entries = build_timeline_with_durations(dsl.scene)
    msg = next(e for e in entries if e["id"] == "m1")
    assert msg["image_url"] == f"{BASE_URL}/uploads/x.png"


def test_build_timeline_with_durations_at_matches_build_timeline():
    """✅ 同一 scene 的 appeared_at 与 build_timeline 的 at 完全一致 — 时间码和模板 TIMELINE 对齐。"""
    dsl = make_dsl(intro_effect="scanline")
    timeline = build_timeline(dsl.scene)
    entries = build_timeline_with_durations(dsl.scene)
    timeline_at = [t["at"] for t in timeline]
    entries_at = [e["at"] for e in entries]
    assert entries_at == timeline_at


def test_build_timeline_with_durations_does_not_mutate_existing_build_timeline():
    """✅ 调用 build_timeline_with_durations 不影响 build_timeline 的返回值。"""
    dsl = make_dsl()
    before = build_timeline(dsl.scene)
    _ = build_timeline_with_durations(dsl.scene)
    after = build_timeline(dsl.scene)
    assert before == after


def test_build_timeline_with_durations_does_not_break_html_render():
    """✅ build_timeline_with_durations 与渲染管线解耦 —— 不会改 HTML 产物。"""
    dsl = make_dsl()
    html_before = render_dsl(dsl)
    _ = build_timeline_with_durations(dsl.scene)
    html_after = render_dsl(dsl)
    assert html_before == html_after
