#!/usr/bin/env python3
"""img-decorate · 水印/圆角/拼接（F-F20）。"""

from __future__ import annotations

import sys
from pathlib import Path

from atelier.server.visual import svgkit as sk

FONT_CANDIDATES = (
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _font(size: int):
    from PIL import ImageFont

    for cand in FONT_CANDIDATES:
        if Path(cand).exists():
            try:
                return ImageFont.truetype(cand, size)
            except OSError:
                continue
    return ImageFont.load_default()


def main() -> int:
    params, out, _ = sk.skill_argv(desc="img-decorate")
    paths = [Path(x.strip()) for x in str(params.get("images") or "").splitlines() if x.strip()]
    if not paths:
        print("img-decorate: images 至少给一个路径（每行一个）", file=sys.stderr)
        return 2
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print(f"img-decorate: 图片不存在：{', '.join(missing)}", file=sys.stderr)
        return 2
    op = str(params.get("op") or "watermark")
    if op not in ("watermark", "round", "stack"):
        print(f"img-decorate: op 非法 {op!r}，可选 watermark/round/stack", file=sys.stderr)
        return 2
    if op == "stack" and len(paths) < 2:
        print("img-decorate: 拼接（stack）至少要 2 张图", file=sys.stderr)
        return 2

    from PIL import Image, ImageDraw

    out.mkdir(parents=True, exist_ok=True)

    if op == "stack":
        imgs = [Image.open(p).convert("RGB") for p in paths]
        target_w = max(im.width for im in imgs)
        scaled = []
        for im in imgs:
            ratio = target_w / im.width
            scaled.append(im.resize((target_w, round(im.height * ratio)), Image.LANCZOS))
        total_h = sum(im.height for im in scaled) + 8 * (len(scaled) - 1)
        canvas = Image.new("RGB", (target_w, total_h), "#FFFFFF")
        y = 0
        for im in scaled:
            canvas.paste(im, (0, y))
            y += im.height + 8
        dst = out / f"stack-{target_w}x{total_h}.png"
        canvas.save(dst, "PNG")
        print(f"img-decorate: 拼接 {len(scaled)} 张 → {target_w}×{total_h}")
        sk.emit({
            "artifacts": [{"path": str(dst), "kind": "image", "name": dst.name}],
            "summary": f"拼接 {len(scaled)} 张 → {target_w}×{total_h}",
            "result_markdown": f"已纵向拼接 {len(scaled)} 张图（对齐最宽 {target_w}px，间隔 8px），总高 {total_h}px。",
        })
        return 0

    img = Image.open(paths[0])
    stem = paths[0].stem
    if op == "round":
        radius = int(params.get("radius") or 32)
        mask = Image.new("L", img.size, 0)
        d = ImageDraw.Draw(mask)
        d.rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=radius, fill=255)
        rgba = img.convert("RGBA")
        rgba.putalpha(mask)
        dst = out / f"{stem}-rounded.png"
        rgba.save(dst, "PNG")
        print(f"img-decorate: 圆角 {radius}px → {dst.name}")
        sk.emit({
            "artifacts": [{"path": str(dst), "kind": "image", "name": dst.name}],
            "summary": f"圆角 {radius}px",
            "result_markdown": f"圆角完成（{radius}px，透明 PNG）。角上的透明区在白底页面看是圆角，深色页面同理。",
        })
        return 0

    # watermark
    text = str(sk.load_params(params, "text", required=True, label="水印文字") or "").strip()
    tile = str(params.get("tile") or "tile") == "tile"
    try:
        opacity = min(100, max(1, int(params.get("opacity") or 18)))
    except (TypeError, ValueError):
        opacity = 18
    base = img.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = _font(max(20, base.width // 28))
    alpha = int(255 * opacity / 100)
    from PIL import Image

    probe = Image.new("RGBA", (10, 10))
    pd = ImageDraw.Draw(probe)
    box = pd.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    if tile:
        step_x, step_y = tw + base.width // 6, th + base.height // 6
        y = 0
        while y < base.height + th:
            x = 0
            while x < base.width + tw:
                draw.text((x, y), text, font=font, fill=(128, 128, 128, alpha))
                x += step_x
            y += step_y
    else:
        draw.text((base.width - tw - 40, base.height - th - 40), text, font=font, fill=(128, 128, 128, alpha))
    result = Image.alpha_composite(base, layer).convert("RGB")
    dst = out / f"{stem}-watermark.png"
    result.save(dst, "PNG")
    print(f"img-decorate: 水印「{text}」（{'平铺' if tile else '单角'}，透明度 {opacity}%）")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "image", "name": dst.name}],
        "summary": f"水印完成（{'平铺' if tile else '单角'}，{opacity}%）",
        "result_markdown": f"水印完成：「{text}」{'平铺' if tile else '右下单角'}，透明度 {opacity}%。防盗图够用；正式品牌露出建议另出矢量版。",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
