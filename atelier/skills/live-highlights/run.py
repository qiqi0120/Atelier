#!/usr/bin/env python3
"""live-highlights · 直播录像高光切片（F-F44，依赖 ffmpeg，能量找点）。"""

from __future__ import annotations

import sys
from pathlib import Path

from atelier.server.media import tools
from atelier.server.visual import svgkit as sk


def main() -> int:
    params, out, _ = sk.skill_argv(desc="live-highlights")
    src = str(sk.load_params(params, "video", required=True, label="直播录像路径") or "").strip()
    path = Path(src)
    if not path.exists():
        print(f"live-highlights: 录像不存在：{src}", file=sys.stderr)
        return 2
    try:
        count = min(10, max(1, int(params.get("count") or 5)))
        seg = min(600, max(15, int(params.get("duration") or 60)))
    except (TypeError, ValueError):
        print("live-highlights: count/duration 应为整数", file=sys.stderr)
        return 2
    try:
        ff = tools.ffmpeg()
    except tools.MediaToolError as e:
        print(f"live-highlights: {e}", file=sys.stderr)
        return 2

    info = tools.probe(path)
    total = info["duration"] or 0
    if total < seg:
        print(f"live-highlights: 录像只有 {total:.0f}s，不足一段 {seg}s", file=sys.stderr)
        return 2
    rc, s_out, s_err = tools.run(
        [ff, "-i", str(path), "-af", "silencedetect=noise=-30dB:d=2", "-f", "null", "-"], timeout=3600
    )
    import re

    log = s_out + s_err
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    candidates = [0.0] + [e for e in ends if e < total - seg]
    # 均匀取样候选，避免整场都挤在开头
    if len(candidates) > count * 3:
        step = len(candidates) / (count * 3)
        candidates = [candidates[int(i * step)] for i in range(count * 3)]
    starts = sorted(candidates[:count]) if len(candidates) <= count else sorted(candidates[: count * 3])[:count][:count]
    if not starts:
        starts = [total * i / (count + 1) for i in range(1, count + 1)]

    out.mkdir(parents=True, exist_ok=True)
    arts = []
    for i, start in enumerate(starts, 1):
        dst = out / f"live-hl-{i:02d}-{int(start)}s.mp4"
        rc, _o, err = tools.run(
            [ff, "-y", "-ss", f"{start:.2f}", "-i", str(path), "-t", f"{seg}", "-c", "copy", str(dst)]
        )
        if rc != 0:
            print(f"live-highlights: 第 {i} 段失败：{err[-200:]}", file=sys.stderr)
            return 2
        arts.append({"path": str(dst), "kind": "video", "name": dst.name})
    print(f"live-highlights: {len(arts)} 段高光")
    sk.emit({
        "artifacts": arts,
        "summary": f"直播高光 {len(arts)} 段 × {seg}s",
        "result_markdown": (
            f"直播高光 {len(arts)} 段（各 {seg}s）：\n"
            + "\n".join(f"- 段 {i}：起点 {s:.0f}s" for i, s in enumerate(starts, 1))
            + "\n\n依据是音量密度（说话最密集），看不懂内容——弹幕高光请用 clip-cut 的 points 模式手动补。"
        ),
        "starts": starts,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
