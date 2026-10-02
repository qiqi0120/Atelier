#!/usr/bin/env python3
"""audio-denoise · ffmpeg afftdn 降噪（F-F27，依赖本机 ffmpeg）。"""

from __future__ import annotations

import sys
from pathlib import Path

from atelier.server.media import tools
from atelier.server.visual import svgkit as sk


def main() -> int:
    params, out, _ = sk.skill_argv(desc="audio-denoise")
    src = str(sk.load_params(params, "audio", required=True, label="音频路径") or "").strip()
    path = Path(src)
    if not path.exists():
        print(f"audio-denoise: 音频不存在：{src}", file=sys.stderr)
        return 2
    try:
        ff = tools.ffmpeg()  # 缺失 → MediaToolError（含安装指引）
    except tools.MediaToolError as e:
        print(f"audio-denoise: {e}", file=sys.stderr)
        return 2
    strength = str(params.get("strength") or "mild")
    nr = 12 if strength == "mild" else 28
    nf = -80 if strength == "mild" else -70

    out.mkdir(parents=True, exist_ok=True)
    dst = out / f"{path.stem}-denoised.wav"
    cmd = [ff, "-y", "-i", str(path), "-af", f"afftdn=nr={nr}:nf={nf}", str(dst)]
    rc, _o, err = tools.run(cmd)
    if rc != 0:
        print(f"audio-denoise: ffmpeg 失败（rc={rc}）：{err[-300:]}", file=sys.stderr)
        return 2
    print(f"audio-denoise: 完成（{strength}, nr={nr}）→ {dst.name}")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "audio", "name": dst.name}],
        "summary": f"降噪完成（{strength}）",
        "result_markdown": f"降噪完成：ffmpeg afftdn，强度 {strength}（nr={nr}）。风噪/电流声重的素材可跑 strong 再听一遍。",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
