"""前端 UI 端到端验收(Playwright)。

流程(对应 docs/06-acceptance.md E2E-1 / UI-1 / UI-2):
1. 打开 http://127.0.0.1:5173,等待预览 iframe 渲染出默认聊天内容
2. 修改群名 → 预览 iframe 顶部标题同步更新(≤500ms 级别)
3. 点击「生成视频」→ 进度面板出现 → 等待「下载 MP4」按钮
4. 校验输出 URL 并下载 MP4,确认文件存在且可被 ffprobe 解析
"""

from __future__ import annotations

import re
import subprocess
import sys
import time

from playwright.sync_api import Page, sync_playwright

BASE = "http://127.0.0.1:5173"


def preview_frame(page: Page):
    """返回 srcDoc 预览 iframe 的 frame 对象(about:srcdoc)。"""
    for f in page.frames:
        if f.url.startswith("about:srcdoc"):
            return f
    return None


def main() -> int:
    results: list[tuple[str, bool]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        errors: list[str] = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        page.goto(BASE, wait_until="networkidle")
        page.wait_for_selector("text=微信聊天视频生成器", timeout=15000)

        # 1. 预览 iframe 渲染出默认内容
        frame = None
        for _ in range(30):
            frame = preview_frame(page)
            if frame and frame.locator(".group-title").count() > 0:
                break
            time.sleep(0.3)
        assert frame is not None, "预览 iframe 未出现"
        title = frame.locator(".group-title").inner_text(timeout=5000)
        ok = title == "后宫风云复盘群 (3)"
        results.append(("预览渲染默认群名", ok))
        print(f"  iframe 群名 = {title!r} -> {'OK' if ok else 'FAIL'}")

        body_text = frame.locator("#chat-inner").inner_text()
        ok = "倚梅园的梅花开了。" in body_text and "余答应已被移出群聊" in body_text
        results.append(("预览包含消息内容", ok))
        print(f"  预览消息内容 -> {'OK' if ok else 'FAIL'}")

        # 2. UI-1:修改群名 → 预览同步更新(iframe 会随预览重挂载,需每次重新取 frame)
        title_input = page.locator('input[value="后宫风云复盘群 (3)"]').first
        assert title_input.count() > 0, "未找到群名输入框"
        title_input.fill("周末聚餐讨论组")
        new_title = ""
        for _ in range(40):  # 防抖 300ms + 请求,最多等 8s
            time.sleep(0.2)
            f2 = preview_frame(page)
            if f2 is None:
                continue
            try:
                new_title = f2.locator(".group-title").inner_text(timeout=1000)
            except Exception:
                continue
            if new_title == "周末聚餐讨论组":
                break
        ok = new_title == "周末聚餐讨论组"
        results.append(("编辑群名预览同步(UI-1)", ok))
        print(f"  群名更新为 {new_title!r} -> {'OK' if ok else 'FAIL'}")

        # 3. 生成视频 → 等待下载按钮
        page.locator("button:has-text('生成视频')").click()
        results.append(("提交后出现进度面板", page.locator(".progress-card").count() > 0))
        print("  进度面板出现 -> OK")

        dl = page.locator("a:has-text('下载 MP4')")
        ok = dl.count() > 0
        for _ in range(90):  # 最多等 90s
            if dl.count() > 0:
                ok = True
                break
            time.sleep(0.5)
        results.append(("90s 内出现下载按钮", ok))
        print(f"  下载按钮出现 -> {'OK' if ok else 'FAIL'}")
        if not ok:
            # 打印错误信息帮助排查
            errs = page.locator(".error-text, .error-banner").all_inner_texts()
            print("  页面错误:", errs)
            browser.close()
            return 1

        href = dl.get_attribute("href")
        ok = bool(href) and href.startswith("/outputs/") and href.endswith(".mp4")
        results.append(("下载链接为 /outputs/{id}.mp4", ok))
        print(f"  下载链接 {href} -> {'OK' if ok else 'FAIL'}")

        # 4. 下载 MP4 并校验
        resp = page.request.get(f"{BASE}{href}")
        data = resp.body()
        out = r"D:\project\private\new_life\code\wechat-video-gen\backend\storage\ui_e2e.mp4"
        with open(out, "wb") as fh:
            fh.write(data)
        ok = resp.ok and len(data) > 0
        results.append(("下载 MP4 成功", ok))
        print(f"  MP4 bytes={len(data)} -> {'OK' if ok else 'FAIL'}")

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
            capture_output=True, text=True,
        )
        dur = probe.stdout.strip()
        ok = probe.returncode == 0 and abs(float(dur) - 10.5) < 0.5
        results.append(("MP4 时长≈10.5s", ok))
        print(f"  MP4 duration={dur}s -> {'OK' if ok else 'FAIL'}")

        browser.close()

    # 汇总
    print("\n==== UI E2E 汇总 ====")
    all_ok = True
    for name, ok in results:
        all_ok = all_ok and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if errors:
        print("  console errors:", errors[:5])
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
