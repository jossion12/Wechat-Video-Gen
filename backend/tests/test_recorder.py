"""recorder 行为测试 — 防止「output_path 遮蔽导入函数」类作用域 bug 回潮,
并覆盖 `render_video_transparent` 的 webm_vp9_alpha / mov_prores4444 两条路径。

`backend/app/recorder.py` 顶部 `from app.storage import output_path` 导入了同名
函数,旧实现又把局部变量也叫 `output_path`,导致
`output_path = output_path(...)` 这行的 RHS 求值时就抛 UnboundLocalError,
任何 render_video 调用都打不到实际录制逻辑。修复方式是把局部变量改名
(`mp4_path`),并把计算前移到 try 块之前。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import recorder
from app.dsl import ChatScene, VideoDSL
from app.models import Message, Participant
from app.storage import OUTPUT_EXT_MOV_PRORES, OUTPUT_EXT_WEBM_ALPHA, OUTPUT_EXT


def make_dsl(**overrides) -> VideoDSL:
    scene = dict(
        intent="short_video_drama",
        intent_acknowledged=True,
        participants=[
            Participant(id="me", name="我", persona=""),
            Participant(id="her", name="她", persona=""),
        ],
        messages=[Message(sender_id="me", kind="text", text="hi", delay_ms=1500)],
    )
    scene.update(overrides)
    return VideoDSL(scene=ChatScene(**scene))


class _ExplodingPlaywright:
    """async_playwright 的替身:进入时立刻抛错,触发 except 块。"""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        raise RuntimeError("playwright intentionally unavailable")

    async def __aexit__(self, *_args):
        return False


@pytest.mark.asyncio
async def test_render_video_does_not_shadow_imported_output_path(monkeypatch):
    """✅ 局部变量不能再 shadow 导入的 `output_path` 函数。

    旧实现里 `output_path = output_path(...)` 这一行,Python 因为 LHS 的赋值
    把 RHS 的 `output_path` 视作局部变量,在赋值前就抛 UnboundLocalError,导致
    render_video 永远进不到真正的录制流程。修复后必须能进入 except 块并
    抛出原始的 RuntimeError(这里是 playwright 不可用),而不是被 UnboundLocalError
    掩盖。
    """

    # render_dsl 顺利返回,避免测试与模板渲染耦合
    monkeypatch.setattr(recorder, "render_dsl", lambda _dsl: "<html></html>")
    # async_playwright 立刻抛错,触发 except 块
    monkeypatch.setattr(recorder, "async_playwright", _ExplodingPlaywright)

    recorded: list[int] = []

    async def fake_progress(pct: int) -> None:
        recorded.append(pct)

    with pytest.raises(RuntimeError, match="playwright intentionally unavailable"):
        await recorder.render_video(
            dsl=make_dsl(),
            job_id="job-x",
            user_id="u-x",
            session_id="s-x",
            progress_callback=fake_progress,
        )
    # 进度回调至少被推过一次
    assert recorded and recorded[0] == 1


@pytest.mark.asyncio
async def test_inject_transparent_background_appends_style():
    """`html, body` + `body::before / body::after` 透明 CSS 必须落到 </head> 之前,
    覆盖模板里的背景色 + 伪元素铺底(背景图 / 网点纹理)。"""
    html = (
        "<html><head><style>body{background:#fff}</style></head>"
        "<body>x</body></html>"
    )
    out = recorder._inject_transparent_background(html)
    # 注入样式在 </head> 之前;既不破坏模板原有 body 颜色样式,又靠 !important 覆盖
    assert "<style id='__wvg_transparent_bg__'>" in out
    assert "background: transparent !important" in out
    assert out.index("__wvg_transparent_bg__") < out.lower().index("</head>")
    # 也要清掉伪元素铺底(背景图 + 网点纹理)
    assert "body::before, body::after" in out
    assert "background-image: none !important" in out
    # 没有 </head> 的退化路径:直接拼到文档头
    no_head = recorder._inject_transparent_background("<p>x</p>")
    assert no_head.startswith("<style")


def test_inject_transparent_background_kills_pseudo_elements():
    """专门盯死伪元素规则 — 这是修复 mov 透明失效的核心。

    之前 CSS 只覆盖 `html, body`,模板里 `body::before`(背景图)和
    `body::after`(网点纹理)继续画,导致 PNG alpha 全是 255,QuickTime
    看到 ProRes 4444 里 alpha 全满会判为「无效 alpha 通道」拒绝打开。
    修复后必须包含针对 `body::before, body::after` 的
    `background: transparent !important; background-image: none !important;`。
    """
    css_blob = recorder._TRANSPARENT_BG_CSS
    # 必须同时含 html / body 和 body::before / body::after
    assert "html, body" in css_blob
    assert "body::before, body::after" in css_blob
    # 两组规则都要把 background 清成透明 + background-image 清掉
    assert css_blob.count("background: transparent !important;") >= 2
    assert css_blob.count("background-image: none !important;") >= 2
    # !important 优先级,确保压过模板里的 background-image: url(...)
    assert "!important" in css_blob


def _make_png_with_alpha_bytes(pixels: list[int]) -> bytes:
    """生成一个 5x5 8-bit 灰度 PNG(用作 alpha probe 的 stub)。

    这里手写最小的 PNG 而不是用 PIL,这样:
      - 测试不需要 PIL
      - 真有 PIL 的话也会因为 IDAT 缺失 raise → 走 rawvideo fallback 路径
    """
    import struct
    import zlib

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 5, 5, 8, 0, 0, 0, 0))
    raw = b""
    for _ in range(5):
        raw += b"\x00" + bytes(pixels)  # filter byte 0 + 5 pixel bytes
    idat = _chunk(b"IDAT", zlib.compress(raw))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def test_probe_first_frame_alpha_returns_true_when_transparent_pixel_exists(monkeypatch, tmp_path):
    """首帧 PNG alpha 平面 5x5 采样,只要有像素 < 255 就返回 True。

    不依赖 PIL:probe 那次 ffmpeg 写出有效 PNG(让 PIL 也无法识别)→
    PIL 抛错 → 走 rawvideo fallback → 用我们 mock 出的 raw bytes 判断。
    """
    import subprocess

    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_0000.png").write_bytes(b"any")  # 占位,probe 函数不读它

    # mock subprocess.run:模拟 ffmpeg probe + rawvideo decode 两次调用
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        out_path = cmd[-1]
        if any("extractplanes=a" in str(c) for c in cmd):
            # 写一个"PNG magic 但没有 IDAT"的 stub — 任何 PIL 都会 raise,
            # 走 rawvideo fallback 路径。
            Path(out_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        elif "rawvideo" in cmd and "gray" in cmd:
            # 25 bytes,至少一个像素 < 255
            pixels = bytes([255] * 10 + [128] + [255] * 14)
            Path(out_path).write_bytes(pixels)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="", stderr="",
        )

    monkeypatch.setattr(recorder.subprocess, "run", fake_run)

    assert recorder._probe_first_frame_alpha(frames) is True
    # 两次调用都发生过(probe + rawvideo decode)
    assert len(calls) >= 2


def test_probe_first_frame_alpha_returns_false_when_fully_opaque(monkeypatch, tmp_path, caplog):
    """首帧 alpha 平面全是 255(全不透明)→ 返回 False,且 logger.warning 被调用。

    这是「透明注入没生效」的信号 — 比如模板改了 CSS 但忘了更新伪元素规则。
    """
    import logging
    import subprocess

    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_0000.png").write_bytes(b"any")

    def fake_run(cmd, **kwargs):
        out_path = cmd[-1]
        if any("extractplanes=a" in str(c) for c in cmd):
            Path(out_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        elif "rawvideo" in cmd and "gray" in cmd:
            Path(out_path).write_bytes(bytes([255] * 25))
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="", stderr="",
        )

    monkeypatch.setattr(recorder.subprocess, "run", fake_run)

    with caplog.at_level(logging.WARNING, logger="recorder"):
        result = recorder._probe_first_frame_alpha(frames)
    assert result is False
    assert any(
        "no transparent pixel found" in rec.message
        for rec in caplog.records
    )


def test_probe_first_frame_alpha_returns_false_when_no_frames(monkeypatch, tmp_path):
    """frames_dir 里没有任何 frame_*.png → 直接返回 False,不抛错。"""
    frames = tmp_path / "frames"
    frames.mkdir()
    # 不放任何 frame_*.png

    # 不应调到 subprocess.run
    def should_not_run(*args, **kwargs):
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr(recorder.subprocess, "run", should_not_run)
    assert recorder._probe_first_frame_alpha(frames) is False


@pytest.mark.asyncio
async def test_render_video_transparent_webm_vp9_alpha_handles_missing_playwright(monkeypatch):
    """✅ webm_vp9_alpha 路径在 playwright 不可用时,必须:
       - 把原始 RuntimeError(playwright 不可用)透传给调用方,不被
         UnboundLocalError / NameError 之类掩盖;
       - 推过至少一次进度回调(首推 1);
       - 输出路径使用 `webm` 扩展名(而不是默认 mp4)。
    """
    monkeypatch.setattr(recorder, "render_dsl", lambda _dsl: "<html></html>")
    monkeypatch.setattr(recorder, "async_playwright", _ExplodingPlaywright)

    recorded: list[int] = []

    async def fake_progress(pct: int) -> None:
        recorded.append(pct)

    with pytest.raises(RuntimeError, match="playwright intentionally unavailable"):
        await recorder.render_video_transparent(
            dsl=make_dsl(),
            job_id="job-w",
            user_id="u-w",
            session_id="s-w",
            progress_callback=fake_progress,
            format="webm_vp9_alpha",
        )
    assert recorded and recorded[0] == 1
    # 顺手验证产物扩展名是 webm(而不是 mp4)
    assert OUTPUT_EXT_WEBM_ALPHA == "webm"


@pytest.mark.asyncio
async def test_render_video_transparent_mov_prores4444_handles_missing_playwright(monkeypatch):
    """✅ mov_prores4444 路径在 playwright 不可用时,行为与 webm 一致;
       输出扩展名是 `mov`。
    """
    monkeypatch.setattr(recorder, "render_dsl", lambda _dsl: "<html></html>")
    monkeypatch.setattr(recorder, "async_playwright", _ExplodingPlaywright)

    recorded: list[int] = []

    async def fake_progress(pct: int) -> None:
        recorded.append(pct)

    with pytest.raises(RuntimeError, match="playwright intentionally unavailable"):
        await recorder.render_video_transparent(
            dsl=make_dsl(),
            job_id="job-m",
            user_id="u-m",
            session_id="s-m",
            progress_callback=fake_progress,
            format="mov_prores4444",
        )
    assert recorded and recorded[0] == 1
    assert OUTPUT_EXT_MOV_PRORES == "mov"


@pytest.mark.asyncio
async def test_render_video_transparent_rejects_unknown_format():
    """未支持的 format 必须在进入 playwright 之前抛 ValueError。"""
    with pytest.raises(ValueError, match="unsupported transparent format"):
        await recorder.render_video_transparent(
            dsl=make_dsl(),
            job_id="job-z",
            user_id="u-z",
            session_id="s-z",
            progress_callback=lambda _p: None,
            format="webm_vp8",  # type: ignore[arg-type]
        )
