#!/usr/bin/env python3
"""meme · 上下大字梗图（F-F13，Pillow PNG）。"""

from __future__ import annotations

import sys
from pathlib import Path

from atelier.server.visual import svgkit as sk

SIZE = 800
FONT_CANDIDATES = (
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def load_font(size: int):
    from PIL import ImageFont

    for cand in FONT_CANDIDATES:
        if Path(cand).exists():
            try:
                return ImageFont.truetype(cand, size)
            except OSError:
                continue
    return ImageFont.load_default()


def draw_text_block(draw, text: str, y_center: int, fill: str, stroke: str) -> None:
    font = load_font(72)
    lines = sk.wrap_cjk(text, 11)[:2]
    line_h = 86
    total = len(lines) * line_h
    y = y_center - total / 2 + 6
    from PIL import Image

    dummy = Image.new("RGB", (10, 10))
    from PIL import ImageDraw

    d = ImageDraw.Draw(dummy)
    for ln in lines:
        box = d.textbbox((0, 0), ln, font=font)
        w = box[2] - box[0]
        draw.text(((SIZE - w) / 2, y), ln, font=font, fill=fill,
                  stroke_width=4, stroke_fill=stroke)
        y += line_h


def main() -> int:
    params, out, _ = sk.skill_argv(desc="meme")
    top = str(params.get("top_text") or "").strip()
    bottom = str(sk.load_params(params, "bottom_text", required=True, label="下方大字（或上下任一）") or "").strip()
    if not top and not bottom:
        print("meme: 至少给 top_text 或 bottom_text 之一", file=sys.stderr)
        return 2
    from PIL import Image, ImageDraw

    base = str(params.get("base_image") or "").strip()
    p = sk.PALETTES.get(str(params.get("theme") or "ink"), sk.PALETTES["ink"])
    if base:
        try:
            img = Image.open(base).convert("RGB")
        except OSError as e:
            print(f"meme: 底图打不开：{base}（{e}）", file=sys.stderr)
            return 2
        side = min(img.size)
        left = (img.width - side) // 2
        top_y = (img.height - side) // 2
        img = img.crop((left, top_y, left + side, top_y + side)).resize((SIZE, SIZE))
    else:
        img = Image.new("RGB", (SIZE, SIZE), p["bg"])
    draw = ImageDraw.Draw(img)
    ink, stroke = p["fg"], "#FFFFFF"
    if top:
        draw_text_block(draw, top, 110, ink, stroke)
    if bottom:
        draw_text_block(draw, bottom, SIZE - 110, ink, stroke)

    out.mkdir(parents=True, exist_ok=True)
    png_path = out / f"{sk.slugify(bottom or top)}-meme.png"
    img.save(png_path, "PNG")
    print(f"meme: 已生成（{'底图' if base else '纯色底'} 800×800）")
    sk.emit({
        "artifacts": [{"path": str(png_path), "kind": "image", "name": png_path.name}],
        "summary": f"梗图已生成：{len(top)}上/{len(bottom)}下字",
        "result_markdown": (
            f"梗图已生成（{'底图版' if base else '纯色底版'}，800×800 PNG）。上下字压图，"
            "字体用系统中文黑体；想换底图重跑给 base_image。"
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
