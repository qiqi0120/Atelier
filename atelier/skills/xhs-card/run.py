#!/usr/bin/env python3
"""xhs-card · 小红书知识卡确定性渲染器。

有 Pillow -> PNG；无 Pillow -> SVG（矢量降级，中文无损）。
标准库只依赖：zlib/struct 未使用，SVG 路径零第三方依赖。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path

THEMES = {
    "warm": {"bg": ("#FFF7ED", "#FFE8D6"), "fg": "#3B2F2F", "accent": "#E8590C", "sub": "#8A6E5F"},
    "cool": {"bg": ("#F1F5F9", "#DBEAFE"), "fg": "#1F2937", "accent": "#1D4ED8", "sub": "#5B6B7F"},
    "ink": {"bg": ("#FFFFFF", "#F3F4F6"), "fg": "#111827", "accent": "#000000", "sub": "#4B5563"},
}

SLUG_OK = set("abcdefghijklmnopqrstuvwxyz0123456789-")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="xhs-card renderer")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--out", default=os.environ.get("ATELIER_OUT", "."))
    ap.add_argument("--project", default=os.environ.get("ATELIER_PROJECT", "default"))
    return ap.parse_args(argv)


def emit(payload: dict) -> None:
    sys.stdout.write("ATELIER_RESULT " + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def slugify(text: str, fallback: str = "card") -> str:
    out = []
    for ch in text.lower():
        if "a" <= ch <= "z" or "0" <= ch <= "9" or ch in SLUG_OK:
            out.append(ch)
        elif ch in " _-/":
            out.append("-")
        if len(out) >= 24:
            break
    s = "".join(out).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s or fallback


def char_width(ch: str) -> float:
    """CJK/全角按 1 em，ASCII 按 0.55 em 估算。"""
    o = ord(ch)
    if o < 0x2E80:
        return 0.55
    return 1.0


#: CJK 避头尾：这些字符不允许出现在行首（标点/收尾符）
#: 换行时若下一个字符属于此类，就让它「挤」在当前行末尾（追い込み），而不是甩到下一行。
NO_LINE_START = "。，、；：？！）」』】》〉…·%,.;:?!)]}>\"'"


def wrap(text: str, max_em: float) -> list[str]:
    lines: list[str] = []
    cur = ""
    cur_w = 0.0
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur, cur_w = "", 0.0
            continue
        w = char_width(ch)
        if cur_w + w > max_em and cur:
            # 避头尾：标点不落行首，允许当前行轻微超宽把它带出去
            if ch in NO_LINE_START:
                cur += ch
                cur_w += w
                continue
            lines.append(cur)
            cur, cur_w = "", 0.0
        cur += ch
        cur_w += w
    if cur:
        lines.append(cur)
    return lines


def split_cards(body: str, count: int) -> list[str]:
    body = (body or "").strip()
    if not body:
        return []
    paras = [p.strip() for p in body.split("\n") if p.strip()]
    if len(paras) >= count:
        chunks: list[list[str]] = [[] for _ in range(count)]
        per = len(paras) / count
        for i, p in enumerate(paras):
            chunks[min(count - 1, int(i / per))].append(p)
        return ["\n".join(c).strip() for c in chunks]
    # 段落不足：按句号二次切分
    units: list[str] = []
    for p in paras:
        buf = ""
        for ch in p:
            buf += ch
            if ch in "。！？!?\n":
                if buf.strip():
                    units.append(buf.strip())
                buf = ""
        if buf.strip():
            units.append(buf.strip())
    if not units:
        return [body]
    if len(units) <= count:
        return units
    chunks = [[] for _ in range(count)]
    per = len(units) / count
    for i, u in enumerate(units):
        chunks[min(count - 1, int(i / per))].append(u)
    return ["".join(c) for c in chunks]


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def render_svg(card: dict, w: int, h: int, theme: str) -> str:
    t = THEMES[theme]
    pad = int(w * 0.0667)
    usable = w - 2 * pad
    fs_title = int(w * 0.0778)  # ~84 @1080
    fs_body = int(w * 0.0481)  # ~52 @1080
    title_lines = wrap(card["title"], usable / fs_title)[:2]
    body_lines: list[str] = []
    for para in card["lines"]:
        body_lines.extend(wrap(para, usable / fs_body))
        body_lines.append("")
    body_lines = body_lines[:14]
    n = card["index"]
    total = card["total"]
    y = pad + fs_title
    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" font-family="PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif">'
        ),
        ("<defs>"),
        (
            f'<linearGradient id="g{n}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" stop-color="{t["bg"][0]}"/><stop offset="100%" stop-color="{t["bg"][1]}"/>'
        ),
        "</linearGradient></defs>",
        f'<rect width="{w}" height="{h}" fill="url(#g{n})"/>',
        f'<rect x="{pad}" y="{pad - fs_title // 2}" width="96" height="10" fill="{t["accent"]}"/>',
    ]
    for ln in title_lines:
        parts.append(
            f'<text x="{pad}" y="{y}" font-size="{fs_title}" font-weight="700" fill="{t["fg"]}">{esc(ln)}</text>'
        )
        y += int(fs_title * 1.25)
    y += int(fs_body * 0.6)
    for ln in body_lines:
        if ln:
            parts.append(
                f'<text x="{pad}" y="{y}" font-size="{fs_body}" fill="{t["fg"]}" '
                f'fill-opacity="0.88">{esc(ln)}</text>'
            )
        y += int(fs_body * 1.6)
    foot = h - pad // 2
    parts.append(
        f'<text x="{pad}" y="{foot}" font-size="{int(fs_body * 0.8)}" fill="{t["sub"]}">'
        f'{n:02d}/{total:02d}</text>'
    )
    cta = card.get("cta") or ""
    if cta:
        parts.append(
            f'<text x="{w - pad}" y="{foot}" font-size="{int(fs_body * 0.8)}" fill="{t["accent"]}" '
            f'text-anchor="end">{esc(cta)}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def render_png(card: dict, w: int, h: int, theme: str, font_path: str | None) -> str:
    """返回 PNG 路径。Pillow 或中文字体缺失时抛 ImportError，由调用方回落 SVG。"""
    from PIL import Image, ImageDraw, ImageFont

    t = THEMES[theme]
    pad = int(w * 0.0667)
    usable = w - 2 * pad
    fs_title = int(w * 0.0778)
    fs_body = int(w * 0.0481)
    img = Image.new("RGB", (w, h), t["bg"][0])
    d = ImageDraw.Draw(img)
    for y in range(h):
        k = y / max(1, h - 1)
        c0 = tuple(int(t["bg"][0][i : i + 2], 16) for i in (1, 3, 5))
        c1 = tuple(int(t["bg"][1][i : i + 2], 16) for i in (1, 3, 5))
        d.line([(0, y), (w, y)], fill=tuple(int(c0[i] + (c1[i] - c0[i]) * k) for i in range(3)))
    d.rectangle([pad, pad - fs_title // 2, pad + 96, pad - fs_title // 2 + 10], fill=t["accent"])
    if not font_path:
        raise ImportError("no CJK font available for Pillow rendering")
    f_title = ImageFont.truetype(font_path, fs_title)
    f_body = ImageFont.truetype(font_path, fs_body)
    f_foot = ImageFont.truetype(font_path, int(fs_body * 0.8))
    y = pad + fs_title
    for ln in wrap(card["title"], usable / fs_title)[:2]:
        d.text((pad, y - fs_title), ln, font=f_title, fill=t["fg"])
        y += int(fs_title * 1.25)
    y += int(fs_body * 0.6)
    for para in card["lines"]:
        for ln in wrap(para, usable / fs_body):
            if y > h - pad:
                break
            d.text((pad, y - fs_body), ln, font=f_body, fill=t["fg"])
            y += int(fs_body * 1.6)
        y += int(fs_body * 0.4)
    d.text((pad, h - pad), f"{card['index']:02d}/{card['total']:02d}", font=f_foot, fill=t["sub"])
    if card.get("cta"):
        d.text((pad, h - pad), card["cta"], font=f_foot, fill=t["accent"], anchor="la")
    return img  # type: ignore[return-value]


def find_cjk_font() -> str | None:
    for p in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ):
        if Path(p).exists():
            return p
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        params = json.loads(args.params or "{}")
    except json.JSONDecodeError as e:
        print(f"xhs-card: --params 不是合法 JSON：{e}", file=sys.stderr)
        return 2
    title = str(params.get("title") or "").strip()
    body = str(params.get("body") or "").strip()
    if not body:
        print("xhs-card: 缺少 body（正文素材），无法切分卡片", file=sys.stderr)
        return 2
    try:
        count = int(params.get("count") or 3)
    except (TypeError, ValueError):
        print(f"xhs-card: count 非法：{params.get('count')!r}，应为 1–9 的整数", file=sys.stderr)
        return 2
    if not 1 <= count <= 9:
        print(f"xhs-card: count={count} 越界，允许 1–9", file=sys.stderr)
        return 2
    size = str(params.get("size") or "1080×1440").replace("x", "×").replace("*", "×")
    try:
        w, h = (int(x) for x in size.split("×"))
    except ValueError:
        print(f"xhs-card: size 非法：{size!r}，应为 宽×高（如 1080×1440）", file=sys.stderr)
        return 2
    theme = str(params.get("theme") or "warm")
    if theme not in THEMES:
        print(f"xhs-card: 未知 theme {theme!r}，可选 {sorted(THEMES)}", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    chunks = split_cards(body, count)
    slug = slugify(title or body[:16])
    cta = str(params.get("cta") or "").strip()

    font_path = find_cjk_font()
    use_png = False
    if font_path:
        try:
            import PIL  # noqa: F401

            use_png = True
        except ImportError:
            print("xhs-card: 未安装 Pillow，改用 SVG 输出（矢量降级，中文无损）", file=sys.stderr)
    else:
        print("xhs-card: 未找到中文字体，改用 SVG 输出", file=sys.stderr)

    cards = [
        {
            "title": title if i == 0 else "",
            "lines": [c] if c else [""],
            "index": i + 1,
            "total": len(chunks),
            "cta": cta,
        }
        for i, c in enumerate(chunks)
    ]
    artifacts: list[dict] = []
    for card in cards:
        name = f"{card['index']:02d}-{slug}"
        if use_png:
            try:
                img = render_png(card, w, h, theme, font_path)
                p = out / f"{name}.png"
                img.save(p)
            except Exception as e:  # noqa: BLE001 -> 降级不静默
                print(f"xhs-card: PNG 渲染失败（{e}），该卡回落 SVG", file=sys.stderr)
                use_png = False
                p = out / f"{name}.svg"
                p.write_text(render_svg(card, w, h, theme), encoding="utf-8")
        else:
            p = out / f"{name}.svg"
            p.write_text(render_svg(card, w, h, theme), encoding="utf-8")
        print(f"xhs-card: 已生成 {p.name}（{w}×{h}）")
        artifacts.append({"path": str(p), "kind": "image", "name": p.name})

    prev = out / "preview.html"
    imgs = [a["name"] for a in artifacts]
    prev.write_text(
        "<!doctype html><meta charset='utf-8'><title>xhs-card 预览</title>"
        "<style>body{font-family:system-ui;background:#111;color:#eee;margin:0;padding:24px}"
        "figure{display:inline-block;margin:0 16px 16px 0}img{width:270px;border-radius:8px}"
        "figcaption{font-size:12px;color:#999}</style>"
        + "".join(f"<figure><img src='{html.escape(n)}'><figcaption>{html.escape(n)}</figcaption></figure>"
                  for n in imgs)
        + f"<p>{len(imgs)} 张 · {w}×{h} · theme={theme}</p>",
        encoding="utf-8",
    )
    artifacts.append({"path": str(prev), "kind": "html", "name": prev.name})
    fmt = "PNG" if use_png else "SVG"
    print(f"xhs-card: 完成，{len(imgs)} 张 {fmt} 卡片，目录 {out}")
    emit(
        {
            "artifacts": artifacts,
            "summary": f"{len(imgs)} 张 {w}×{h} 卡片（{fmt}）",
            "format": fmt,
            "count": len(imgs),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
