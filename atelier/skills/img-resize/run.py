#!/usr/bin/env python3
"""img-resize · 尺寸/裁剪/补边/转格式/压目标大小（F-F19）。"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from atelier.server.visual import svgkit as sk

FMT_EXT = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg", "webp": ".webp"}


def encode(img, fmt: str, quality: int) -> bytes:
    buf = io.BytesIO()
    if fmt in ("jpeg", "jpg"):
        img = img.convert("RGB")
        img.save(buf, "JPEG", quality=quality, optimize=True)
    elif fmt == "webp":
        img.save(buf, "WEBP", quality=quality)
    else:
        img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def main() -> int:
    params, out, _ = sk.skill_argv(desc="img-resize")
    src = str(sk.load_params(params, "image", required=True, label="图片路径") or "").strip()
    path = Path(src)
    if not path.exists():
        print(f"img-resize: 图片不存在：{src}", file=sys.stderr)
        return 2
    from PIL import Image

    img = Image.open(path)
    orig_size = img.size
    mode = str(params.get("mode") or "resize")

    def _dim(key: str) -> int | None:
        v = params.get(key)
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            print(f"img-resize: {key} 应为整数", file=sys.stderr)
            raise SystemExit(2)

    width, height = _dim("width"), _dim("height")
    if width or height:
        if mode == "cover":
            tw, th = width or height or img.width, height or width or img.height
            ratio = max(tw / img.width, th / img.height)
            img = img.resize((round(img.width * ratio), round(img.height * ratio)), Image.LANCZOS)
            l = (img.width - tw) // 2
            t = (img.height - th) // 2
            img = img.crop((l, t, l + tw, t + th))
        elif mode == "pad":
            tw, th = width or height or img.width, height or width or img.height
            ratio = min(tw / img.width, th / img.height)
            scaled = img.resize((round(img.width * ratio), round(img.height * ratio)), Image.LANCZOS)
            bg_raw = str(params.get("bg") or "#FFFFFF")
            canvas = Image.new("RGB" if bg_raw.upper() != "none" else "RGBA", (tw, th), bg_raw)
            canvas.paste(scaled, ((tw - scaled.width) // 2, (th - scaled.height) // 2))
            img = canvas
        else:
            ratio = (width / img.width) if width else (height / img.height)
            img = img.resize((round(img.width * ratio), round(img.height * ratio)), Image.LANCZOS)

    fmt = (
        str(params.get("format") or "").lower()
        or ("jpeg" if path.suffix.lower() in (".jpg", ".jpeg")
            else "webp" if path.suffix.lower() == ".webp"
            else "png")
    )
    quality = 92
    data = encode(img, fmt, quality)
    compressed_note = ""
    target_kb = params.get("target_kb")
    if target_kb not in (None, ""):
        try:
            limit = int(target_kb) * 1024
        except (TypeError, ValueError):
            print("img-resize: target_kb 应为整数", file=sys.stderr)
            return 2
        lo, hi = 5, 95
        best = None
        while lo <= hi:
            mid = (lo + hi) // 2
            data = encode(img, fmt, mid)
            if len(data) <= limit:
                best = (mid, len(data))
                lo = mid + 1
            else:
                hi = mid - 1
        if best is None:
            data = encode(img, fmt, 5)
            compressed_note = (
                f"压不进 {int(target_kb)}KB（质量 5 仍为 {len(data)//1024}KB）——分辨率太大，"
                "先缩小尺寸再压。以下产物是质量 5 的结果，如实报告，不硬塞。"
            )
            quality = 5
        else:
            quality, size = best
            data = encode(img, fmt, quality)
            compressed_note = f"质量二分定在 {quality}，压到 {size//1024}KB（目标 {int(target_kb)}KB）"

    out.mkdir(parents=True, exist_ok=True)
    ext = FMT_EXT.get(fmt, path.suffix)
    dst = out / f"{path.stem}-resized{ext}"
    Path(dst).write_bytes(data)
    print(f"img-resize: {orig_size} → {img.size}，{fmt} q={quality}，{len(data)//1024}KB")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "image", "name": dst.name}],
        "summary": f"{orig_size[0]}×{orig_size[1]} → {img.width}×{img.height} · {fmt} · {len(data)//1024}KB",
        "result_markdown": (
            f"处理完成：{orig_size[0]}×{orig_size[1]} → {img.width}×{img.height}（{mode}），"
            f"格式 {fmt}，质量 {quality}，{len(data)//1024}KB。" + (f"\n\n⚠️ {compressed_note}" if compressed_note else "")
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
