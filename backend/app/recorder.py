"""Playwright 录制 + ffmpeg 转码 — 见 docs/01-architecture.md、docs/05-deployment.md。

流程:渲染 HTML → Chromium 播放动画并录制 webm → ffmpeg 转 h264 mp4(1080×1920)。
录制期间每 500ms 回调一次进度;失败时清理临时文件,不产出半成品 MP4。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable

from playwright.async_api import async_playwright

from app.dsl import VideoDSL
from app.renderer import render_dsl, resolve_duration_ms
from app.storage import OUTPUTS

logger = logging.getLogger("recorder")

ProgressCallback = Callable[[int], Awaitable[None]]

CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--font-render-hinting=none",
]

VIEWPORT = {"width": 1080, "height": 1920}


async def render_video(
    dsl: VideoDSL, job_id: str, progress_callback: ProgressCallback
) -> Path:
    """渲染 → 录制 → 转码,返回输出 mp4 路径。任何异常都会清理临时产物并抛出。"""
    html = render_dsl(dsl)
    duration_ms = resolve_duration_ms(dsl.scene)
    duration_s = duration_ms / 1000.0
    output_path = OUTPUTS / f"{job_id}.mp4"
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

        logger.info("Encoding %s -> %s", webm_path.name, output_path.name)
        await progress_callback(92)
        _encode_webm_to_mp4(webm_path, output_path, duration_s)
        await progress_callback(99)
        return output_path
    except Exception:
        output_path.unlink(missing_ok=True)  # 失败不产出 MP4
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)  # 自动清理 webm 临时文件


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
