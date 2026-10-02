#!/usr/bin/env python3
"""beat-cut · 按 BPM 网格卡点（F-F38，诚实：BPM 由用户给，不做真实节拍检测）。"""

from __future__ import annotations

import sys
from pathlib import Path

from atelier.server.media import tools
from atelier.server.visual import svgkit as sk


def main() -> int:
    params, out, _ = sk.skill_argv(desc="beat-cut")
    paths = [Path(x.strip()) for x in str(params.get("images") or "").splitlines() if x.strip()]
    if not paths:
        print("beat-cut: images 至少 1 张（每行一个路径）", file=sys.stderr)
        return 2
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print(f"beat-cut: 图片不存在：{', '.join(missing)}", file=sys.stderr)
        return 2
    audio = str(sk.load_params(params, "audio", required=True, label="音乐路径") or "").strip()
    if not Path(audio).exists():
        print(f"beat-cut: 音乐不存在：{audio}", file=sys.stderr)
        return 2
    try:
        bpm = min(220, max(40, float(params.get("bpm") or 120)))
        beats = max(1, int(params.get("beats_per_cut") or 4))
    except (TypeError, ValueError):
        print("beat-cut: bpm/beats_per_cut 应为数字", file=sys.stderr)
        return 2
    try:
        ff = tools.ffmpeg()
    except tools.MediaToolError as e:
        print(f"beat-cut: {e}", file=sys.stderr)
        return 2

    per = beats * 60.0 / bpm  # 每张秒数
    info = tools.probe(audio)
    music_dur = info["duration"] or 0
    need = int((music_dur / per) + 0.999) if music_dur else len(paths)
    # 图片循环补齐到音乐长度
    cycle = (paths * ((need // len(paths)) + 1))[: max(need, 1)]
    n = len(cycle)

    cmd = [ff, "-y"]
    for p in cycle:
        cmd += ["-loop", "1", "-t", f"{per:.3f}", "-i", str(p)]
    cmd += ["-i", audio]
    concat = ";".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vout]"
    cmd += ["-filter_complex", concat, "-map", "[vout]", "-map", f"{n}:a",
            "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "25", "-shortest"]
    dst = out / "beat-cut.mp4"
    cmd.append(str(dst))
    rc, _o, err = tools.run(cmd, timeout=3600)
    if rc != 0:
        print(f"beat-cut: ffmpeg 失败（rc={rc}）：{err[-400:]}", file=sys.stderr)
        return 2
    print(f"beat-cut: {n} 张按 {bpm}BPM/{beats}拍 卡点 → {dst.name}")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "video", "name": dst.name}],
        "summary": f"卡点视频：{n} 张 · {bpm}BPM · {per:.2f}s/张",
        "result_markdown": (
            f"卡点视频完成：{n} 张图，BPM {bpm} 每 {beats} 拍一切（{per:.2f}s/张），音乐 {Path(audio).name}。"
            "\n\n诚实说明：拍点按你给的 BPM 均分，非真实节拍检测——鼓点复杂的歌可微调 beats_per_cut。"
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
