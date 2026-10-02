#!/usr/bin/env python3
"""chroma-key · 绿/蓝幕色距抠像（F-F21）。"""

from __future__ import annotations

import sys
from pathlib import Path

from atelier.server.visual import svgkit as sk

KEY_RGB = {"green": (60, 200, 80), "blue": (50, 110, 220)}


def main() -> int:
    params, out, _ = sk.skill_argv(desc="chroma-key")
    src = str(sk.load_params(params, "image", required=True, label="绿幕图片路径") or "").strip()
    path = Path(src)
    if not path.exists():
        print(f"chroma-key: 图片不存在：{src}", file=sys.stderr)
        return 2
    key_color = str(params.get("key_color") or "green")
    if key_color not in KEY_RGB:
        print(f"chroma-key: key_color 只支持 green/blue（{key_color!r}）", file=sys.stderr)
        return 2
    try:
        tolerance = min(120, max(10, int(params.get("tolerance") or 60)))
    except (TypeError, ValueError):
        tolerance = 60
    background = str(params.get("background") or "").strip()

    from PIL import Image

    img = Image.open(path).convert("RGB")
    kr, kg, kb = KEY_RGB[key_color]
    rgba = img.convert("RGBA")
    data = rgba.load()
    keyed = 0
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, _a = data[x, y]
            dist = ((r - kr) ** 2 + (g - kg) ** 2 + (b - kb) ** 2) ** 0.5
            if dist < tolerance:
                data[x, y] = (r, g, b, 0)
                keyed += 1
            elif dist < tolerance * 1.6:  # 边缘半透明，去绿边
                alpha = int(255 * (dist - tolerance) / (tolerance * 0.6))
                data[x, y] = (r, g, b, max(0, min(255, alpha)))
    total = rgba.width * rgba.height
    ratio = keyed / total
    if ratio < 0.05:
        print(
            f"chroma-key: 只抠掉 {ratio:.0%} 的像素——这不像 {key_color} 幕布图。"
            "检查 key_color 或调大 tolerance（当前 "
            f"{tolerance}）",
            file=sys.stderr,
        )
        return 2

    result = rgba
    bg_note = "透明背景（PNG alpha）"
    if background:
        if background.startswith("#"):
            canvas = Image.new("RGBA", rgba.size, background)
        elif Path(background).exists():
            bg = Image.open(background).convert("RGBA")
            ratio_bg = max(rgba.width / bg.width, rgba.height / bg.height)
            bg = bg.resize((round(bg.width * ratio_bg), round(bg.height * ratio_bg)), Image.LANCZOS)
            l = (bg.width - rgba.width) // 2
            t = (bg.height - rgba.height) // 2
            canvas = bg.crop((l, t, l + rgba.width, t + rgba.height))
        else:
            print(f"chroma-key: 背景既不是 #色值 也不是存在的图片：{background}", file=sys.stderr)
            return 2
        canvas.alpha_composite(rgba)
        result = canvas
        bg_note = f"背景 {background[:24]}"

    out.mkdir(parents=True, exist_ok=True)
    dst = out / f"{path.stem}-keyed.png"
    result.save(dst, "PNG")
    print(f"chroma-key: 抠掉 {ratio:.0%} 像素，{bg_note}")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "image", "name": dst.name}],
        "summary": f"抠像完成（去 {ratio:.0%}，{bg_note}）",
        "result_markdown": (
            f"抠像完成：{key_color} 幕、容差 {tolerance}，去除 {ratio:.0%} 像素，{bg_note}。"
            "边缘做了半透明过渡去绿边；发丝级精度需要语义分割模型（本仓库暂无，如实说明）。"
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
