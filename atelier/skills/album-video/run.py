#!/usr/bin/env python3
"""album-video · 图片 + Ken Burns + 转场 + BGM（F-F37，依赖 ffmpeg）。"""

from __future__ import annotations

import sys
from pathlib import Path

from atelier.server.media import tools
from atelier.server.visual import svgkit as sk


def main() -> int:
    params, out, _ = sk.skill_argv(desc="album-video")
    paths = [Path(x.strip()) for x in str(params.get("images") or "").splitlines() if x.strip()]
    if len(paths) < 2:
        print("album-video: 至少 2 张图（每行一个路径，按顺序）", file=sys.stderr)
        return 2
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print(f"album-video: 图片不存在：{', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        per = min(15, max(1, float(params.get("per_image") or 3)))
    except (TypeError, ValueError):
        per = 3.0
    size = str(params.get("size") or "1080x1920")
    if size not in ("1080x1920", "1920x1080", "1080x1080"):
        print("album-video: size 支持 1080x1920 / 1920x1080 / 1080x1080", file=sys.stderr)
        return 2
    sw, sh = (int(x) for x in size.split("x"))
    audio = str(params.get("audio") or "").strip()
    if audio and not Path(audio).exists():
        print(f"album-video: BGM 不存在：{audio}", file=sys.stderr)
        return 2
    try:
        ff = tools.ffmpeg()
    except tools.MediaToolError as e:
        print(f"album-video: {e}", file=sys.stderr)
        return 2

    n = len(paths)
    cmd = [ff, "-y"]
    for p in paths:
        cmd += ["-loop", "1", "-t", f"{per:.2f}", "-i", str(p)]
    if audio:
        cmd += ["-i", audio]
    zooms = []
    for i in range(n):
        direction = "zoom+0.0012" if i % 2 == 0 else "if(lte(zoom,1.0),1.25,max(1.001,zoom-0.0012))"
        zooms.append(
            f"[{i}:v]scale={sw*2}:{sh*2},"
            f"zoompan=z='{direction}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={int(per*25)}:s={sw}x{sh}:fps=25,setsar=1[v{i}]"
        )
    xfade = []
    if n > 1:
        for i in range(n - 1):
            offset = per * (i + 1) - 0.5
            xfade.append(f"[v{i}][v{i+1}]xfade=transition=fade:duration=0.5:offset={offset:.2f}[x{i}];")
    chain = ";".join(zooms) + ";" + "".join(xfade)
    last = f"[x{n-2}]" if n > 1 else "[v0]"
    cmd += ["-filter_complex", chain, "-map", last]
    if audio:
        cmd += ["-map", f"{n}:a", "-shortest"]
    cmd += ["-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "25"]
    dst = out / "album-video.mp4"
    cmd.append(str(dst))
    rc, _o, err = tools.run(cmd, timeout=3600)
    if rc != 0:
        print(f"album-video: ffmpeg 失败（rc={rc}）：{err[-400:]}", file=sys.stderr)
        return 2
    print(f"album-video: {n} 张 → {dst.name}（{size}，每张 {per}s）")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "video", "name": dst.name}],
        "summary": f"相册视频：{n} 张 · {size} · {per}s/张",
        "result_markdown": (
            f"相册视频完成：{n} 张图，Ken Burns 缓动（缩放方向交替）+ 淡入转场"
            + (f"，BGM {Path(audio).name}" if audio else "（无 BGM，可用 audio-mix 再配）") + "。"
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
