#!/usr/bin/env python3
"""audio-mix · 人声+BGM 混音，可闪避（F-F28，依赖 ffmpeg）。"""

from __future__ import annotations

import sys
from pathlib import Path

from atelier.server.media import tools
from atelier.server.visual import svgkit as sk


def main() -> int:
    params, out, _ = sk.skill_argv(desc="audio-mix")
    voice = str(sk.load_params(params, "voice", required=True, label="人声路径") or "").strip()
    bgm = str(sk.load_params(params, "bgm", required=True, label="BGM 路径") or "").strip()
    for p, label in ((voice, "人声"), (bgm, "BGM")):
        if not Path(p).exists():
            print(f"audio-mix: {label}不存在：{p}", file=sys.stderr)
            return 2
    try:
        bgm_vol = min(1.0, max(0.0, float(params.get("bgm_volume") or 0.2)))
    except (TypeError, ValueError):
        bgm_vol = 0.2
    duck = str(params.get("duck") or "on") == "on"
    try:
        ff = tools.ffmpeg()
    except tools.MediaToolError as e:
        print(f"audio-mix: {e}", file=sys.stderr)
        return 2

    out.mkdir(parents=True, exist_ok=True)
    dst = out / "mix-down.wav"
    if duck:
        afilter = (
            f"[1:a]volume={bgm_vol}[bgm];"
            "[bgm][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=50:release=400[ducked];"
            "[0:a][ducked]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
    else:
        afilter = f"[1:a]volume={bgm_vol}[bgm];[0:a][bgm]amix=inputs=2:duration=first[aout]"
    cmd = [ff, "-y", "-i", voice, "-i", bgm, "-filter_complex", afilter, "-map", "[aout]", str(dst)]
    rc, _o, err = tools.run(cmd)
    if rc != 0:
        print(f"audio-mix: ffmpeg 失败（rc={rc}）：{err[-300:]}", file=sys.stderr)
        return 2
    print(f"audio-mix: 完成（bgm={bgm_vol}{'，闪避 on' if duck else ''}）→ {dst.name}")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "audio", "name": dst.name}],
        "summary": f"混音完成（bgm={bgm_vol}，闪避 {'on' if duck else 'off'}）",
        "result_markdown": (
            f"混音完成：人声为主轨，BGM {bgm_vol}" +
            ("，sidechain 真闪避（人声出现 BGM 自动压低）" if duck else "，固定音量直混") +
            "。以 duration=first 为准：人声播完即结束。"
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
