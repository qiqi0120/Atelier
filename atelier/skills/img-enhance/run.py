#!/usr/bin/env python3
"""img-enhance · 放大/降噪/锐化（F-F18，Pillow 传统算法，非 AI 超分）。"""

from __future__ import annotations

import sys
from pathlib import Path

from atelier.server.visual import svgkit as sk


def main() -> int:
    params, out, _ = sk.skill_argv(desc="img-enhance")
    src = str(sk.load_params(params, "image", required=True, label="图片路径") or "").strip()
    path = Path(src)
    if not path.exists():
        print(f"img-enhance: 图片不存在：{src}", file=sys.stderr)
        return 2
    try:
        scale = min(4.0, max(1.0, float(params.get("scale") or 2)))
    except (TypeError, ValueError):
        print("img-enhance: scale 应为 1~4 的数字", file=sys.stderr)
        return 2
    denoise = str(params.get("denoise") or "mild")
    try:
        sharpen = min(100, max(0, int(params.get("sharpen") or 60)))
    except (TypeError, ValueError):
        sharpen = 60

    from PIL import Image, ImageFilter

    img = Image.open(path)
    orig_size = img.size
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    # 次序：先降噪（小图上去噪更快）→ 放大 → 锐化
    if denoise == "mild":
        img = img.filter(ImageFilter.MedianFilter(3))
    elif denoise == "strong":
        img = img.filter(ImageFilter.MedianFilter(5))
    if scale > 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    if sharpen > 0:
        percent = 60 + sharpen * 1.2
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=int(percent), threshold=3))

    out.mkdir(parents=True, exist_ok=True)
    dst = out / f"{path.stem}-enhanced.png"
    img.save(dst, "PNG")
    print(f"img-enhance: {orig_size} → {img.size}（denoise={denoise}, sharpen={sharpen}）")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "image", "name": dst.name}],
        "summary": f"增强完成 {orig_size[0]}×{orig_size[1]} → {img.width}×{img.height}",
        "result_markdown": (
            f"增强完成：{orig_size[0]}×{orig_size[1]} → {img.width}×{img.height}，"
            f"降噪 {denoise}，锐化 {sharpen}/100。**传统算法增强，非 AI 超分**——"
            "文字/图形效果好；人像大倍率建议配专门超分模型。"
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
