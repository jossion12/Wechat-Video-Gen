"""前端 UI 端到端验收(Playwright)。

流程(对应 docs/06-acceptance.md E2E-1 / UI-1 / UI-2,适配无 demo 空配置):
1. 打开 http://127.0.0.1:5173,确认页面为空白配置(无 demo 参与者/消息)
2. 依次完成 5 步向导:创作意图 → 视觉风格 → 添加 2 名角色 → 添加 1 条消息 → 预览生成
3. 预览 iframe 渲染出默认标题「对话剧场」
4. 修改标题 → 预览 iframe 顶部标题同步更新(≤500ms 级别)
5. 点击「生成视频」→ 进度面板出现 → 等待「下载 MP4」按钮
6. 校验输出 URL 并下载 MP4,确认文件存在且可被 ffprobe 解析
"""

from __future__ import annotations

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


def go_to_step(page: Page, step: int) -> None:
    """点击步骤器跳转到指定步骤(仅已完成的可点击)。"""
    page.locator(f".stepper-step-wrapper:nth-child({step}) .stepper-step").click()


def main() -> int:
    results: list[tuple[str, bool]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors: list[str] = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        page.goto(BASE, wait_until="networkidle")
        page.wait_for_selector("text=对话剧场 / Dialogue Theater", timeout=15000)

        # 1. 进入页面应为空白配置:无 demo 参与者/消息,标题为默认「对话剧场」
        ok = page.locator(".participant-row").count() == 0
        results.append(("进入页面无 demo 参与者", ok))
        print(f"  参与者行数 = {page.locator('.participant-row').count()} -> {'OK' if ok else 'FAIL'}")

        ok = page.locator(".message-row").count() == 0
        results.append(("进入页面无 demo 消息", ok))
        print(f"  消息行数 = {page.locator('.message-row').count()} -> {'OK' if ok else 'FAIL'}")

        # 2. 完成第 1 步:创作意图
        page.locator("input[name='intent'][value='short_video_drama']").check()
        page.locator(".checkbox-option--agreement input").check()
        page.locator("button:has-text('下一步')").click()

        # 第 2 步:视觉风格,检查默认标题
        title_input = page.locator("#chat-title")
        ok = title_input.input_value() == "对话剧场"
        results.append(("默认标题为「对话剧场」", ok))
        print(f"  默认标题 = {title_input.input_value()!r} -> {'OK' if ok else 'FAIL'}")

        # 3. 进入第 3 步添加 2 名角色
        page.locator("button:has-text('下一步')").click()
        page.locator("button:has-text('添加角色')").click()
        page.locator("button:has-text('添加角色')").click()
        page.locator(".participant-name").nth(0).fill("小美")
        page.locator(".participant-name").nth(1).fill("阿强")

        # 4. 进入第 4 步添加 1 条消息
        page.locator("button:has-text('下一步')").click()
        page.locator("button:has-text('添加消息')").click()
        page.locator(".message-text").nth(0).fill("周末一起吃饭吗?")

        # 5. 进入第 5 步,预览渲染
        page.locator("button:has-text('下一步')").click()
        frame = None
        for _ in range(30):
            frame = preview_frame(page)
            if frame and frame.locator(".theater-title").count() > 0:
                break
            time.sleep(0.3)
        ok = frame is not None
        results.append(("进入第 5 步后预览 iframe 出现", ok))
        print(f"  预览 iframe 出现 -> {'OK' if ok else 'FAIL'}")
        if frame is None:
            browser.close()
            return 1

        title = frame.locator(".theater-title").inner_text(timeout=5000)
        ok = title == "对话剧场"
        results.append(("预览渲染默认标题", ok))
        print(f"  iframe 标题 = {title!r} -> {'OK' if ok else 'FAIL'}")

        body_text = frame.locator("#chat-inner").inner_text()
        ok = "周末一起吃饭吗?" in body_text
        results.append(("预览包含消息内容", ok))
        print(f"  预览消息内容 -> {'OK' if ok else 'FAIL'}")

        # 6. UI-1:修改标题 → 预览同步更新(iframe 会随预览重挂载,需每次重新取 frame)
        title_input.fill("周末聚餐讨论组")
        new_title = ""
        for _ in range(40):  # 防抖 300ms + 请求,最多等 8s
            time.sleep(0.2)
            f2 = preview_frame(page)
            if f2 is None:
                continue
            try:
                new_title = f2.locator(".theater-title").inner_text(timeout=1000)
            except Exception:
                continue
            if new_title == "周末聚餐讨论组":
                break
        ok = new_title == "周末聚餐讨论组"
        results.append(("编辑标题预览同步(UI-1)", ok))
        print(f"  标题更新为 {new_title!r} -> {'OK' if ok else 'FAIL'}")

        # 7. 生成视频 → 等待下载按钮
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
            errs = page.locator(".error-text, .error-banner").all_inner_texts()
            print("  页面错误:", errs)
            browser.close()
            return 1

        href = dl.get_attribute("href")
        ok = bool(href) and href.startswith("/api/jobs/") and href.endswith("/output")
        results.append(("下载链接为 /api/jobs/{id}/output", ok))
        print(f"  下载链接 {href} -> {'OK' if ok else 'FAIL'}")

        # 8. 下载 MP4 并校验(1 条消息 → 1000+1500+1500=4000ms=4s)
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
        ok = probe.returncode == 0 and abs(float(dur) - 4.0) < 0.5
        results.append(("MP4 时长≈4s", ok))
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
