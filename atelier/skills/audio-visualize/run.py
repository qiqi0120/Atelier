#!/usr/bin/env python3
"""audio-visualize · 波形图 PNG（F-F29，ffmpeg showwavespic）。"""

from __future__ import annotations

import sys
from pathlib import Path

from atelier.server.media import tools
from atelier.server.visual import svgkit as sk


def main() -> int:
    params, out, _ = sk.skill_argv(desc="audio-visualize")
    src = str(sk.load_params(params, "audio", required=True, label="音频路径") or "").strip()
    path = Path(src)
    if not path.exists():
        print(f"audio-visualize: 音频不存在：{src}", file=sys.stderr)
        return 2
    try:
        width = min(3840, max(320, int(params.get("width") or 1600)))
        height = min(2160, max(120, int(params.get("height") or 400)))
    except (TypeError, ValueError):
        print("audio-visualize: width/height 应为整数", file=sys.stderr)
        return 2
    try:
        ff = tools.ffmpeg()
    except tools.MediaToolError as e:
        print(f"audio-visualize: {e}", file=sys.stderr)
        return 2

    out.mkdir(parents=True, exist_ok=True)
    dst = out / f"{path.stem}-waveform.png"
    cmd = [ff, "-y", "-i", str(path), "-filter_complex",
           f"showwavespic=s={width}x{height}:colors=#059669", "-frames:v", "1", str(dst)]
    rc, _o, err = tools.run(cmd)
    if rc != 0:
        print(f"audio-visualize: ffmpeg 失败（rc={rc}）：{err[-300:]}", file=sys.stderr)
        return 2
    print(f"audio-visualize: 波形图 {width}×{height} → {dst.name}")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "image", "name": dst.name}],
        "summary": f"波形图 {width}×{height}",
        "result_markdown": f"波形图已生成（{width}×{height} PNG，showwavespic）。动态频谱视频需 ffmpeg 滤镜链定制，本版静态波形（如实说明）。",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
