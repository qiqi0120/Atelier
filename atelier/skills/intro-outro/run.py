#!/usr/bin/env python3
"""intro-outro · 片头/片尾卡 + 拼接（F-F39，Pillow + ffmpeg）。"""

from __future__ import annotations

import sys
from pathlib import Path

from atelier.server.media import tools
from atelier.server.visual import svgkit as sk

FONT_CANDIDATES = (
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
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


def make_card(text: str, sub: str, w: int, h: int) -> Path:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (w, h), "#0F2E22")
    draw = ImageDraw.Draw(img)
    font_t = _font(w // 12)
    font_s = _font(w // 28)
    lines = sk.wrap_cjk(text, w // (w // 12) - 2)[:2]
    total = len(lines) * (w // 10)
    y = h / 2 - total / 2 - (30 if sub else 0)
    for ln in lines:
        box = draw.textbbox((0, 0), ln, font=font_t)
        draw.text(((w - box[2] + box[0]) / 2, y), ln, font=font_t, fill="#ECFDF5")
        y += w // 10
    if sub:
        box = draw.textbbox((0, 0), sub, font=font_s)
        draw.text(((w - box[2] + box[0]) / 2, y + 30), sub, font=font_s, fill="#6EE7B7")
    tmp = Path(out or ".") / "card-tmp.png"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    img.save(tmp, "PNG")
    return tmp


def main() -> int:
    global out
    params, out, _ = sk.skill_argv(desc="intro-outro")
    src = str(sk.load_params(params, "video", required=True, label="正片路径") or "").strip()
    path = Path(src)
    if not path.exists():
        print(f"intro-outro: 正片不存在：{src}", file=sys.stderr)
        return 2
    title = str(sk.load_params(params, "title", required=True, label="片头标题") or "").strip()
    sub = str(params.get("subtitle") or "").strip()
    outro = str(params.get("outro_text") or "").strip()
    try:
        dur = min(10, max(1, float(params.get("duration") or 2)))
    except (TypeError, ValueError):
        dur = 2.0
    try:
        ff = tools.ffmpeg()
    except tools.MediaToolError as e:
        print(f"intro-outro: {e}", file=sys.stderr)
        return 2

    info = tools.probe(path)
    w, h = info["width"] or 1080, info["height"] or 1920
    w, h = w // 2 * 2, h // 2 * 2
    out.mkdir(parents=True, exist_ok=True)

    parts: list[Path] = []
    head = make_card(title, sub, w, h)
    head_vid = out / "intro.mp4"
    rc, _o, err = tools.run(
        [ff, "-y", "-loop", "1", "-t", f"{dur}", "-i", str(head),
         "-vf", f"fade=t=in:st=0:d=0.4,fade=t=out:st={dur - 0.4}:d=0.4",
         "-r", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(head_vid)]
    )
    if rc != 0:
        print(f"intro-outro: 片头卡合成失败：{err[-200:]}", file=sys.stderr)
        return 2
    parts.append(head_vid)

    if outro:
        tail = make_card(outro, "", w, h)
        tail_vid = out / "outro.mp4"
        rc, _o, err = tools.run(
            [ff, "-y", "-loop", "1", "-t", f"{dur}", "-i", str(tail),
             "-vf", f"fade=t=in:st=0:d=0.4,fade=t=out:st={dur-0.4}:d=0.4",
             "-r", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tail_vid)]
        )
        if rc != 0:
            print(f"intro-outro: 片尾卡合成失败：{err[-200:]}", file=sys.stderr)
            return 2
        parts.append(path)
        parts.append(tail_vid)
    else:
        parts.append(path)

    lst = out / "concat-list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    dst = out / f"{path.stem}-with-intro.mp4"
    rc, _o, err = tools.run(
        [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(dst)]
    )
    if rc != 0:
        print(f"intro-outro: 拼接失败（编码参数不一致时改用重编码）：{err[-200:]}", file=sys.stderr)
        # 诚实回退：重编码拼接
        rc, _o, err = tools.run(
            [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", str(dst)], timeout=1800
        )
        if rc != 0:
            print(f"intro-outro: 重编码拼接仍失败：{err[-300:]}", file=sys.stderr)
            return 2
    n_head = 1 + (1 if outro else 0)
    print(f"intro-outro: 完成（片头{'' if not outro else ' + 片尾'}，{dur}s/卡）")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "video", "name": dst.name}],
        "summary": f"片头片尾完成（{n_head} 卡 × {dur}s）",
        "result_markdown": f"完成：{'片头 + 片尾' if outro else '仅片头'}各 {dur}s（淡入淡出），已拼进「{path.name}」。",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
