#!/usr/bin/env python3
"""clip-cut · 长视频切片（F-F35，points/energy 两种找点，依赖 ffmpeg）。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from atelier.server.media import tools
from atelier.server.visual import svgkit as sk


def parse_point(s: str) -> float:
    s = s.strip()
    if ":" in s:
        parts = [float(x) for x in s.split(":")]
        sec = 0.0
        for x in parts:
            sec = sec * 60 + x
        return sec
    return float(s)


def energy_points(path: Path, count: int, seg: float) -> list[float]:
    """silencedetect 反向：静音区间的「之间」就是说话密集段。"""
    ff = tools.ffmpeg()
    _rc, out, err = tools.run(
        [ff, "-i", str(path), "-af", "silencedetect=noise=-30dB:d=1.5", "-f", "null", "-"], timeout=1800
    )
    log = out + err
    silences: list[tuple[float, float]] = []
    starts = re.findall(r"silence_start: ([\d.]+)", log)
    ends = re.findall(r"silence_end: ([\d.]+)", log)
    for i, s in enumerate(starts):
        e = float(ends[i]) if i < len(ends) else None
        if e is not None:
            silences.append((float(s), e))
    info = tools.probe(path)
    total = info["duration"] or 0
    if total <= 0:
        return []
    # 候选起点：0 与每个 silence_end
    candidates = [0.0] + [e for _, e in silences if e < total - seg]
    scored = []
    for start in candidates:
        seg_end = min(start + seg, total)
        speech = seg_end - start
        for ss, se in silences:
            overlap = max(0.0, min(seg_end, se) - max(start, ss))
            speech -= overlap
        scored.append((speech, start))
    scored.sort(reverse=True)
    picked = sorted(start for _, start in scored[:count])
    return picked


def main() -> int:
    params, out, _ = sk.skill_argv(desc="clip-cut")
    src = str(sk.load_params(params, "video", required=True, label="视频路径") or "").strip()
    path = Path(src)
    if not path.exists():
        print(f"clip-cut: 视频不存在：{src}", file=sys.stderr)
        return 2
    mode = str(params.get("mode") or "energy")
    if mode not in ("points", "energy"):
        print(f"clip-cut: mode 只支持 points/energy（{mode!r}）", file=sys.stderr)
        return 2
    try:
        seg = min(600, max(5, int(params.get("duration") or 45)))
        count = min(10, max(1, int(params.get("count") or 3)))
    except (TypeError, ValueError):
        print("clip-cut: duration/count 应为整数", file=sys.stderr)
        return 2
    try:
        ff = tools.ffmpeg()
    except tools.MediaToolError as e:
        print(f"clip-cut: {e}", file=sys.stderr)
        return 2

    if mode == "points":
        raw = str(sk.load_params(params, "points", required=True, label="时间点") or "")
        starts = [parse_point(x) for x in raw.split(",") if x.strip()]
        if not starts:
            print("clip-cut: points 至少给一个起点（如 30,2:15）", file=sys.stderr)
            return 2
    else:
        starts = energy_points(path, count, seg)
        if not starts:
            print("clip-cut: energy 找点失败（拿不到时长或无有效音频）——改用 mode=points 手动给点", file=sys.stderr)
            return 2

    info = tools.probe(path)
    total = info["duration"] or 0
    out.mkdir(parents=True, exist_ok=True)
    arts = []
    for i, start in enumerate(starts, 1):
        dur = min(seg, max(1.0, total - start)) if total else seg
        dst = out / f"clip-{i:02d}-{int(start)}s.mp4"
        rc, _o, err = tools.run(
            [ff, "-y", "-ss", f"{start:.2f}", "-i", str(path), "-t", f"{dur:.2f}", "-c", "copy", str(dst)]
        )
        if rc != 0:
            print(f"clip-cut: 第 {i} 段切片失败：{err[-200:]}", file=sys.stderr)
            return 2
        arts.append({"path": str(dst), "kind": "video", "name": dst.name})
    print(f"clip-cut: {len(arts)} 段（{mode} 模式）")
    sk.emit({
        "artifacts": arts,
        "summary": f"切片 {len(arts)} 段（{mode}）",
        "result_markdown": (
            f"切片完成：{len(arts)} 段 × ≤{seg}s（{mode} 模式）。\n"
            + "\n".join(f"- 段 {i}：起点 {s:.0f}s" for i, s in enumerate(starts, 1))
            + ("\n\nenergy 模式找的是「说话最密集」段（silencedetect 反推）；纯 BGM 视频请用 points。"
               if mode == "energy" else "")
        ),
        "starts": starts,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
