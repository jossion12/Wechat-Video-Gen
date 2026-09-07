"""Playwright 录制 + ffmpeg 转码 — 见 docs/01-architecture.md、docs/05-deployment.md。

两条产物线:

- 不透明:`render_video` → Chromium 录 webm → ffmpeg 转 h264 mp4(yuv420p,无 alpha)。
  HTML 背景默认是 body 的 CSS 颜色,合成时直接拍死。
- 透明:`render_video_transparent` → 根据 `format` 选 webm_vp9_alpha / mov_prores4444。
  webm_vp9_alpha 走 Chromium 录屏 + ffmpeg 重编码为 VP9+yuva420p(尽量保留 alpha);
  mov_prores4444 走 page.screenshot(omit_background=True) 截 PNG 序列,再 ffmpeg 封 ProRes 4444。

所有路径共用 try/except/finally 模板:失败清理 PNG 序列 / webm / mov,不留半成品。

时间码 JSON(`timeline.json`)与视频产物并行写出,记录 disclaimer / intro / 每条消息
的精确出现 / 消失时间(毫秒,相对视频起点 0)。失败时与视频产物一起清理,避免半成品。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable, Literal

from playwright.async_api import async_playwright

from app.dsl import VideoDSL

from app.renderer import build_timeline_with_durations, render_dsl, resolve_duration_ms
from app.storage import (
    OUTPUT_EXT,
    OUTPUT_EXT_MOV_PRORES,
    OUTPUT_EXT_WEBM_ALPHA,
    output_path,
    remove_timeline,
    timeline_path,
)

logger = logging.getLogger("recorder")

ProgressCallback = Callable[[int], Awaitable[None]]

# MOV ProRes 4444 截图采样率。可按需调整(更高 fps → 更大文件)。
TRANSPARENT_MOV_FPS = 30

CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--font-render-hinting=none",
]

VIEWPORT = {"width": 1080, "height": 1920}

# 注入到 HTML <head> 末尾的样式:把 html / body / body 伪元素背景全部清空。
#
# 模板里所有主题(comic / cyberpunk / ink / noir / pixel / watercolor)都用
# 伪元素铺底:
#   - body::before: 有 background_image_url 时 cover 全屏背景图
#   - body::after: 总是画 z-index:9998 的 radial-gradient 网点纹理
# 只覆盖 html / body 不够,伪元素在 body 之上继续画,Playwright 截到的
# PNG 是 alpha=255 的不透明画面,QuickTime 看到 ProRes 4444 里 alpha 全
# 满会判定为「无效 alpha 通道」拒绝打开。
#
# 因此除了 html / body 本身,还要把 body::before / body::after 的
# background 和 background-image 一起清掉(其它真实元素 — disclaimer-card、
# chat bubble 等 — 不动,它们的 alpha 行为由自身决定)。
#
# 注意:Chromium record_video 默认把页面合成在 opaque backdrop 上,这套 CSS
# 在 Chromium 端只能保证渲染层透明;若要真正的 VP9 alpha 还需要 ffmpeg 配合
# `-pix_fmt yuva420p`(webm_vp9_alpha 路径)。MOV 路径直接走 omit_background
# 截图,alpha 一定会保留。
_TRANSPARENT_BG_CSS = (
    "<style id='__wvg_transparent_bg__'>"
    "html, body {"
    " background: transparent !important;"
    " background-image: none !important;"
    "}"
    "body::before, body::after {"
    " background: transparent !important;"
    " background-image: none !important;"
    "}"
    "</style>"
)


def _inject_transparent_background(html: str) -> str:
    """在 HTML 里追加强制透明的 CSS,不动模板本身。

    CSS 规则见 `_TRANSPARENT_BG_CSS`(覆盖 html/body + body::before/::after)。
    找不到 </head> 时退化为在文档开头插入 — 总比没有好。

    签名 / 行为不变,只是注入的常量内容升级了。
    """
    lower = html.lower()
    idx = lower.rfind("</head>")
    if idx >= 0:
        return html[:idx] + _TRANSPARENT_BG_CSS + html[idx:]
    return _TRANSPARENT_BG_CSS + html


def _write_timeline_json(
    dsl: VideoDSL,
    user_id: str,
    session_id: str,
    job_id: str,
) -> Path:
    """把 `build_timeline_with_durations()` 的结果写到 `timeline.json`,返回落盘路径。

    失败抛 RuntimeError(让上层 except 把它跟视频产物一起清理)。文件是
    `application/json` 文本,排版不锁(前端只 parse 不展示),用 `ensure_ascii=False`
    让中文 / emoji 直接落盘,体积比 ``\\uXXXX`` 转义小一点。
    """
    events = build_timeline_with_durations(dsl.scene)
    payload = {
        "schema_version": "1.0",
        "kind": "chat",
        "job_id": job_id,
        "total_duration_ms": events[-1]["disappeared_at"] if events else 0,
        "entries": events,
    }
    out = timeline_path(user_id, session_id, job_id)
    # ensure_ascii=False + UTF-8 编码 —— 浏览器 / curl 直接打开能看中文;
    # 早期前端如果不读也能 vim 看。
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out


async def render_video(
    dsl: VideoDSL,
    job_id: str,
    user_id: str,
    session_id: str,
    progress_callback: ProgressCallback,
) -> Path:
    """渲染 → 录制 → 转码,返回输出 mp4 路径。任何异常都会清理临时产物并抛出。"""
    html = render_dsl(dsl)
    duration_ms = resolve_duration_ms(dsl.scene)
    duration_s = duration_ms / 1000.0
    # 提前算路径,避免 render_dsl / resolve_duration_ms 抛错时下面的 except
    # 块还在用未赋值的同名变量(原来叫 output_path 会 shadow 导入的函数)
    mp4_path = output_path(user_id, session_id, job_id, OUTPUT_EXT)
    tmp_dir = Path(tempfile.mkdtemp(prefix="wvg-"))
    webm_path: Path | None = None

    try:
        await progress_callback(1)
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=CHROMIUM_ARGS)
            try:
                context = await browser.new_context(
                    viewport=VIEWPORT,
                    device_scale_factor=1,
                    record_video_dir=str(tmp_dir),
                    record_video_size=VIEWPORT,
                )
                page = await context.new_page()
                await page.set_content(html, wait_until="load")
                logger.info("Recording started for %s (%.1fs)", job_id, duration_s)
                video = page.video

                # 等待动画播完(加 0.8s 余量),期间每 500ms 推一次进度
                total_wait = duration_s + 0.8
                start = time.monotonic()
                while True:
                    elapsed = time.monotonic() - start
                    if elapsed >= total_wait:
                        break
                    pct = min(88, int(elapsed / total_wait * 88))
                    await progress_callback(max(pct, 1))
                    await asyncio.sleep(0.5)

                await page.close()
                await context.close()
                if video is None:
                    raise RuntimeError("playwright video recording was not enabled")
                webm_path = Path(await video.path())
            finally:
                await browser.close()

        logger.info("Encoding %s -> %s", webm_path.name, mp4_path.name)
        await progress_callback(92)
        _encode_webm_to_mp4(webm_path, mp4_path, duration_s)
        # 时间码 JSON 与 MP4 同时落地 —— 视频成功才有 timeline。
        # 写在转码成功之后:timeline 数据全部来自 DSL,失败概率极低;
        # 但若这一步抛错,下面的 except 会把 timeline 和 mp4 一起 unlink。
        timeline_out = _write_timeline_json(dsl, user_id, session_id, job_id)
        logger.info("Timeline written: %s", timeline_out.name)
        await progress_callback(99)
        return mp4_path
    except Exception:
        mp4_path.unlink(missing_ok=True)  # 失败不产出 MP4
        remove_timeline(user_id, session_id, job_id)  # timeline.json 与 MP4 同生命周期
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)  # 自动清理 webm 临时文件


async def render_video_transparent(
    dsl: VideoDSL,
    job_id: str,
    user_id: str,
    session_id: str,
    progress_callback: ProgressCallback,
    *,
    format: Literal["webm_vp9_alpha", "mov_prores4444"],
) -> Path:
    """透明背景录制入口。

    `format="webm_vp9_alpha"`:Chromium 录 webm → ffmpeg 重编码为 VP9+yuva420p。
    `format="mov_prores4444"`:逐帧 PNG 截图 → ffmpeg 封 ProRes 4444 (yuva444p10le)。

    任何异常都会清理 webm / PNG 序列 / mov,不产出半成品。
    """
    if format not in ("webm_vp9_alpha", "mov_prores4444"):
        raise ValueError(f"unsupported transparent format: {format!r}")

    html = render_dsl(dsl)
    transparent_html = _inject_transparent_background(html)
    duration_ms = resolve_duration_ms(dsl.scene)
    duration_s = duration_ms / 1000.0

    if format == "webm_vp9_alpha":
        ext = OUTPUT_EXT_WEBM_ALPHA
    else:
        ext = OUTPUT_EXT_MOV_PRORES
    out_path = output_path(user_id, session_id, job_id, ext)
    tmp_dir = Path(tempfile.mkdtemp(prefix="wvg-"))
    frames_dir = tmp_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    try:
        await progress_callback(1)
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=CHROMIUM_ARGS)
            try:
                if format == "webm_vp9_alpha":
                    recorded_webm = await _record_webm_with_transparent_css(
                        browser, transparent_html, duration_s,
                        progress_callback, tmp_dir, job_id,
                    )
                    await progress_callback(92)
                    await _encode_webm_to_webm_alpha(
                        recorded_webm, out_path, duration_s,
                        progress_callback,
                    )
                else:
                    await _capture_png_sequence_for_mov(
                        browser, transparent_html, duration_s,
                        TRANSPARENT_MOV_FPS, frames_dir,
                        progress_callback,
                    )
                    # alpha sanity check:抽首帧 PNG 的 alpha 平面 5x5 采样,
                    # 若全部 alpha=255(=完全不透),说明透明注入没生效,
                    # ProRes 4444 封进去之后 QuickTime 可能会判为"无效
                    # alpha 通道"拒绝打开。这里只 logger.warning,不抛
                    # 错 — 用户可能故意渲染纯不透明画面。helper 内部
                    # 已发 warning,这里不再重复。
                    _probe_first_frame_alpha(frames_dir)
                    await progress_callback(92)
                    _encode_png_sequence_to_mov_prores4444(
                        frames_dir, out_path, TRANSPARENT_MOV_FPS,
                    )
                # 视频产物成功后才落地 timeline.json —— 透明/不透明两条产物线
                # 共用同一份时间码数据,与视频按同一公式算总时长。
                timeline_out = _write_timeline_json(dsl, user_id, session_id, job_id)
                logger.info("Timeline written: %s", timeline_out.name)
                await progress_callback(99)
                size_mb = out_path.stat().st_size / 1024 / 1024
                logger.info(
                    "Transparent render done job=%s format=%s out=%s size=%.1fMB",
                    job_id, format, out_path.name, size_mb,
                )
                return out_path
            finally:
                await browser.close()
    except Exception:
        out_path.unlink(missing_ok=True)  # 失败不产出 webm / mov
        remove_timeline(user_id, session_id, job_id)  # timeline.json 与视频产物同生命周期
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)  # 自动清理临时目录(PNG / 中间 webm)


async def _record_webm_with_transparent_css(
    browser,
    html: str,
    duration_s: float,
    progress_callback: ProgressCallback,
    tmp_dir: Path,
    job_id: str,
) -> Path:
    """Chromium 录制透明背景 webm,返回中间文件路径。"""
    context = await browser.new_context(
        viewport=VIEWPORT,
        device_scale_factor=1,
        record_video_dir=str(tmp_dir),
        record_video_size=VIEWPORT,
    )
    page = await context.new_page()
    await page.set_content(html, wait_until="load")
    logger.info("Transparent webm recording started for %s (%.1fs)", job_id, duration_s)
    video = page.video

    total_wait = duration_s + 0.8
    start = time.monotonic()
    while True:
        elapsed = time.monotonic() - start
        if elapsed >= total_wait:
            break
        pct = min(88, int(elapsed / total_wait * 88))
        await progress_callback(max(pct, 1))
        await asyncio.sleep(0.5)

    await page.close()
    await context.close()
    if video is None:
        raise RuntimeError("playwright video recording was not enabled")
    return Path(await video.path())


async def _capture_png_sequence_for_mov(
    browser,
    html: str,
    duration_s: float,
    fps: int,
    frames_dir: Path,
    progress_callback: ProgressCallback,
) -> int:
    """逐帧截 PNG(带 alpha)保存到 frames_dir,返回实际帧数。

    透明由两层保证:
      (a) `_inject_transparent_background` 在 HTML 里追加的 CSS(见
          `_TRANSPARENT_BG_CSS`)覆盖 `html / body` 以及 `body::before /
          body::after` 的 background / background-image,把页面自身的
          背景、模板背景图、网点纹理全部清掉 — 避免模板伪元素把 alpha
          拍死成 255;
      (b) `page.screenshot(omit_background=True)` 在截图瞬间跳过浏览器
          默认的白色 backdrop,让透明像素真正落到 PNG 的 alpha 通道。

    故意不放 `omit_background=True` 到 `new_context(...)`:实测
    `playwright==1.47.0` 的 `Browser.new_context(...)` 不接受这个 kwarg
    (会抛 `TypeError: unexpected keyword argument 'omit_background'`),
    该 kwarg 是后续版本才加进 new_context 的。把 omit_background 只放
    在 screenshot 调上既兼容 1.47,也够拿到透明 PNG。
    """
    context = await browser.new_context(
        viewport=VIEWPORT,
        device_scale_factor=1,
    )
    page = await context.new_page()
    await page.set_content(html, wait_until="load")

    num_frames = max(1, round(duration_s * fps))
    interval = 1.0 / fps
    logger.info(
        "Transparent png-sequence capturing: %.1fs @ %dfps → %d frames",
        duration_s, fps, num_frames,
    )
    try:
        for i in range(num_frames):
            frame_path = frames_dir / f"frame_{i:04d}.png"
            await page.screenshot(
                path=str(frame_path),
                omit_background=True,
                type="png",
            )
            if i < num_frames - 1:
                await asyncio.sleep(interval)
            # 进度:截图阶段从 1 推到 88(留 92/99 给编码)
            pct = 1 + int((i + 1) / num_frames * 87)
            await progress_callback(pct)
    finally:
        await page.close()
        await context.close()
    return num_frames


def _probe_first_frame_alpha(frames_dir: Path) -> bool:
    """抽 frames_dir 首帧 PNG 的 alpha 平面,5x5 downscale 后采样,
    返回 True 表示至少有一个像素 alpha < 255(即存在透明区域)。

    实现:
      - ffmpeg `-vf extractplanes=a,scale=5:5` 出 5x5 灰度 PNG
      - 优先用 PIL 读像素;没 PIL 就用 ffmpeg 直接出 rawvideo
      - 任何一步失败(probe 报错 / 文件不存在 / 读像素失败)都返回 False
        并 logger.warning — 都是「用户可能没拿到想要的 alpha」信号。
    """
    frame_path = next(iter(sorted(frames_dir.glob("frame_*.png"))), None)
    if frame_path is None or not frame_path.exists():
        logger.warning(
            "Transparent alpha probe: no frame_*.png in %s",
            frames_dir,
        )
        return False

    probe_path = frames_dir / "_alpha_probe.png"
    raw_path = frames_dir / "_alpha_probe.raw"
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-v", "error",
                "-y",
                "-i", str(frame_path),
                "-vf", "extractplanes=a,scale=5:5",
                "-frames:v", "1",
                str(probe_path),
            ],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not probe_path.exists():
            logger.warning(
                "alpha probe ffmpeg failed: %s",
                proc.stderr[-500:] if proc.stderr else "no output",
            )
            return False

        pixels: list[int] = []
        try:
            from PIL import Image  # type: ignore[import-not-found]
            img = Image.open(probe_path).convert("L")
            pixels = list(img.getdata())
        except Exception:  # noqa: BLE001 — fallback 到 rawvideo
            raw = subprocess.run(
                [
                    "ffmpeg", "-v", "error", "-y",
                    "-i", str(probe_path),
                    "-f", "rawvideo", "-pix_fmt", "gray",
                    str(raw_path),
                ],
                capture_output=True, text=True,
            )
            if raw.returncode != 0 or not raw_path.exists():
                logger.warning("alpha probe rawvideo decode failed")
                return False
            pixels = list(raw_path.read_bytes())

        has_transparent = any(p < 255 for p in pixels)
        if not has_transparent:
            logger.warning(
                "Transparent alpha probe: no transparent pixel found in "
                "first frame — output MOV may be rejected by QuickTime "
                "(yuva444p with all-255 alpha).",
            )
        return has_transparent
    finally:
        probe_path.unlink(missing_ok=True)
        raw_path.unlink(missing_ok=True)


def _encode_webm_to_mp4(webm: Path, mp4: Path, duration_s: float) -> None:
    """webm → h264 mp4,精确裁剪到 duration_s,保证时长与 duration_ms 一致。"""
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(webm),
        "-t", f"{duration_s:.3f}",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",
        str(mp4),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-2000:]}")
    if not mp4.exists() or mp4.stat().st_size == 0:
        raise RuntimeError("ffmpeg produced no output file")


async def _encode_webm_to_webm_alpha(
    src_webm: Path,
    dst_webm: Path,
    duration_s: float,
    progress_callback: ProgressCallback | None = None,
) -> None:
    """Chromium 录的 webm → VP9 with alpha webm(yuva420p)。

    默认 libvpx-vp9 是 best quality 单线程,长视频(1080×1920 × 几分钟)可能
    压几十分钟。这里用 `-deadline realtime -cpu-used 8 -threads 4` 让
    libvpx-vp9 软编码也能保持可用速度(10-50x 加速),视觉质量小幅下降
    对透明背景完全够用。

    异步跑 subprocess 并解析 stderr 的 `time=` 字段,把 92%-99% 之间的
    进度平滑推给 progress_callback,避免用户看到「卡在 92%」。节流 0.5s
    防止 ffmpeg 高频输出时 DB / SSE 被刷爆;编码收尾强制推一次 99%。
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(src_webm),
        "-t", f"{duration_s:.3f}",
        "-c:v", "libvpx-vp9",
        "-pix_fmt", "yuva420p",
        "-deadline", "realtime",
        "-cpu-used", "8",
        "-threads", "4",
        "-b:v", "0",
        "-crf", "30",
        "-an",
        str(dst_webm),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stderr is not None

    time_re = re.compile(r"time=(\d+):(\d+):(\d+\.?\d*)")
    # 上游 render_video_transparent 已经推过 92,这里从 92 起算避免重复
    last_pushed = 92
    last_pushed_at = 0.0
    try:
        while True:
            raw = await proc.stderr.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="ignore")
            m = time_re.search(line)
            if not m or progress_callback is None or duration_s <= 0:
                continue
            cur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            pct = 92 + int(min(cur / duration_s, 1.0) * 7)
            now = time.monotonic()
            if pct > last_pushed and (now - last_pushed_at >= 0.5 or pct >= 99):
                last_pushed = pct
                last_pushed_at = now
                await progress_callback(pct)

        rc = await proc.wait()
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()

    # 编码收尾保证推到 99%(即便最后一帧 time= 没达到 duration_s)
    if progress_callback is not None:
        await progress_callback(99)

    if rc != 0:
        try:
            rest = await proc.stderr.read()
        except Exception:
            rest = b""
        err = rest.decode("utf-8", errors="ignore")
        raise RuntimeError(f"ffmpeg failed (rc={rc}): {err[-2000:]}")
    if not dst_webm.exists() or dst_webm.stat().st_size == 0:
        raise RuntimeError("ffmpeg produced no output file")


def _encode_png_sequence_to_mov_prores4444(
    frames_dir: Path, mov_path: Path, fps: int
) -> None:
    """PNG 序列 → ProRes 4444 MOV(yuva444p10le),逐帧精确。"""
    cmd = [
        "ffmpeg",
        "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%04d.png"),
        "-c:v", "prores_ks",
        "-profile:v", "4",
        "-pix_fmt", "yuva444p10le",
        "-an",
        str(mov_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-2000:]}")
    if not mov_path.exists() or mov_path.stat().st_size == 0:
        raise RuntimeError("ffmpeg produced no output file")