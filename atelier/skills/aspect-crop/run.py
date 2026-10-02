#!/usr/bin/env python3
"""aspect-crop · 16:9↔9:16（F-F36，crop/blur 两种，依赖 ffmpeg）。"""

from __future__ import annotations

import sys
from pathlib import Path

from atelier.server.media import tools
from atelier.server.visual import svgkit as sk


def even(n: float) -> int:
    return int(n) // 2 * 2


def main() -> int:
    params, out, _ = sk.skill_argv(desc="aspect-crop")
    src = str(sk.load_params(params, "video", required=True, label="视频路径") or "").strip()
    path = Path(src)
    if not path.exists():
        print(f"aspect-crop: 视频不存在：{src}", file=sys.stderr)
        return 2
    target = str(params.get("target") or "vertical")
    if target not in ("vertical", "horizontal"):
        print("aspect-crop: target 只支持 vertical/horizontal", file=sys.stderr)
        return 2
    mode = str(params.get("mode") or "blur")
    if mode not in ("crop", "blur"):
        print("aspect-crop: mode 只支持 crop/blur", file=sys.stderr)
        return 2
    try:
        ff = tools.ffmpeg()
    except tools.MediaToolError as e:
        print(f"aspect-crop: {e}", file=sys.stderr)
        return 2

    info = tools.probe(path)
    w, h = info["width"], info["height"]
    if not w or not h:
        print("aspect-crop: 拿不到视频尺寸（ffprobe）", file=sys.stderr)
        return 2
    tw, th = (1080, 1920) if target == "vertical" else (1920, 1080)

    if mode == "crop":
        scale = max(tw / w, th / h)
        scaled_w, scaled_h = even(w * scale), even(h * scale)
        vf = (
            f"scale={scaled_w}:{scaled_h},"
            f"crop={tw}:{th}:(iw-{tw})/2:(ih-{th})/2"
        )
    else:
        vf = (
            f"split[a][b];[a]scale={tw}:{th}:force_original_aspect_ratio=increase,"
            f"crop={tw}:{th},gblur=sigma=28[bg];"
            f"[b]scale={tw}:{th}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )

    out.mkdir(parents=True, exist_ok=True)
    dst = out / f"{path.stem}-{target}-{mode}.mp4"
    cmd = [ff, "-y", "-i", str(path), "-vf", vf, "-c:v", "libx264", "-crf", "20", "-c:a", "copy", str(dst)]
    rc, _o, err = tools.run(cmd, timeout=1800)
    if rc != 0:
        print(f"aspect-crop: ffmpeg 失败（rc={rc}）：{err[-300:]}", file=sys.stderr)
        return 2
    print(f"aspect-crop: {w}×{h} → {tw}×{th}（{mode}）")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "video", "name": dst.name}],
        "summary": f"{w}×{h} → {tw}×{th}（{mode}）",
        "result_markdown": (
            f"转换完成：{w}×{h} → {tw}×{th}（{ '中心裁剪' if mode == 'crop' else '模糊垫底' }）。"
            + "主体不居中时 crop 会切掉人，建议 blur。" if mode == "crop" else ""
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
