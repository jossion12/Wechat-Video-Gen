"""recorder 行为测试 — 防止「output_path 遮蔽导入函数」类作用域 bug 回潮。

`backend/app/recorder.py` 顶部 `from app.storage import output_path` 导入了同名
函数,旧实现又把局部变量也叫 `output_path`,导致
`output_path = output_path(...)` 这行的 RHS 求值时就抛 UnboundLocalError,
任何 render_video 调用都打不到实际录制逻辑。修复方式是把局部变量改名
(`mp4_path`),并把计算前移到 try 块之前。
"""

from __future__ import annotations

import pytest

from app import recorder
from app.dsl import ChatScene, VideoDSL
from app.models import Message, Participant


def make_dsl(**overrides) -> VideoDSL:
    scene = dict(
        participants=[
            Participant(id="me", name="我"),
            Participant(id="her", name="她"),
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
    monkeypatch.setattr(recorder, "render_dsl", lambda _dsl, user=None: "<html></html>")
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
