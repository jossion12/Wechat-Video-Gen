"""验收辅助:统计 PNG 帧中指定颜色像素数量(纯标准库,无第三方依赖)。

用法: python check_frame.py <frame.png> <r,g,b> <tol> [<r,g,b> <tol> ...]
"""

from __future__ import annotations

import subprocess
import sys


def rgb_counts(path: str, targets: list[tuple[tuple[int, int, int], int]]) -> dict:
    # 用 ffmpeg 把 PNG 转成 raw RGB,再统计目标颜色
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
    )
    if raw.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {raw.stderr.decode(errors='ignore')[:500]}")
    data = raw.stdout
    w, h = 1080, 1920
    assert len(data) == w * h * 3, f"unexpected frame size {len(data)}"
    counts = {str(t): 0 for t, _ in targets}
    step = w * 3
    for y in range(0, h, 4):          # 隔行采样提速,结果按比例放大
        row = y * step
        for x in range(0, w, 4):
            i = row + x * 3
            r, g, b = data[i], data[i + 1], data[i + 2]
            for (tr, tg, tb), tol in targets:
                if abs(r - tr) <= tol and abs(g - tg) <= tol and abs(b - tb) <= tol:
                    counts[str((tr, tg, tb))] += 1
    return counts


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    path = sys.argv[1]
    args = sys.argv[2:]
    targets = []
    i = 0
    while i < len(args):
        rgb = tuple(int(v) for v in args[i].split(","))
        tol = int(args[i + 1])
        targets.append((rgb, tol))
        i += 2
    counts = rgb_counts(path, targets)
    ok = True
    for (tr, tg, tb), tol in targets:
        c = counts[str((tr, tg, tb))]
        status = "OK" if c > 0 else "MISSING"
        if c == 0:
            ok = False
        print(f"color #{tr:02x}{tg:02x}{tb:02x} tol={tol}: {c} samples -> {status}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
