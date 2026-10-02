#!/usr/bin/env python3
"""quote-card · 16:9 金句卡/数据卡确定性渲染（F-F7，SPEC-13 §1.1）。"""

from __future__ import annotations

import sys

from atelier.server.visual import svgkit as sk

W, H = 1920, 1080


def render(quote: str, attribution: str, theme: dict, dataset: list[tuple[str, str]]) -> str:
    p = theme
    parts = [sk.svg_open(W, H, p["bg"])]
    parts.append(f'<rect x="60" y="60" width="{W-120}" height="{H-120}" rx="28" fill="{p["bg2"]}"/>')
    parts.append(
        f'<rect x="60" y="60" width="14" height="{H-120}" rx="7" fill="{p["accent"]}"/>'
    )
    # 引号装饰
    parts.append(
        f'<text x="170" y="330" font-family="Georgia, serif" font-size="260" fill="{p["accent"]}" opacity="0.35">“</text>'
    )
    # 金句主体：大号换行
    body_font = 92 if len(quote) <= 40 else 72
    lines = sk.wrap_cjk(quote, width=int((W - 480) / (body_font * 1.05)))
    if len(lines) > 4:  # 截断保护，如实提示在 QC 段
        lines = lines[:4]
        lines[3] = lines[3][:-1] + "…"
    y = 430
    for ln in lines:
        parts.append(
            f'<text x="330" y="{y}" font-family="PingFang SC, Microsoft YaHei, sans-serif" '
            f'font-size="{body_font}" font-weight="700" fill="{p["fg"]}">{sk.esc(ln)}</text>'
        )
        y += int(body_font * 1.5)
    # 署名
    if attribution:
        parts.append(
            f'<text x="{W-200}" y="{H-200}" text-anchor="end" font-size="44" fill="{p["sub"]}">'
            f'—— {sk.esc(attribution)}</text>'
        )
    # 数据条
    if dataset:
        n = len(dataset)
        bar_w, bar_h = min(380, (W - 360) // max(n, 1) - 40), 150
        x = 330
        for name, value in dataset:
            parts.append(f'<rect x="{x}" y="{H-360}" width="{bar_w}" height="{bar_h}" rx="16" fill="{p["bg"]}" stroke="{p["line"]}"/>')
            parts.append(
                f'<text x="{x + bar_w/2}" y="{H-300}" text-anchor="middle" font-size="52" '
                f'font-weight="700" fill="{p["accent"]}">{sk.esc(value)}</text>'
            )
            parts.append(
                f'<text x="{x + bar_w/2}" y="{H-240}" text-anchor="middle" font-size="34" fill="{p["sub"]}">{sk.esc(name)}</text>'
            )
            x += bar_w + 40
    parts.append(sk.svg_close())
    return "".join(parts)


HTML_TMPL = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>金句卡预览</title><style>body{{margin:0;background:#fafaf9;display:grid;place-items:center;min-height:100vh}}
img{{max-width:92vw;box-shadow:0 10px 40px rgba(0,0,0,.12);border-radius:12px}}</style></head>
<body><img src="{svg}" alt="金句卡"></body></html>"""


def main() -> int:
    params, out, _project = sk.skill_argv(desc="quote-card")
    quote = str(sk.load_params(params, "quote", required=True, label="金句原文") or "").strip()
    attribution = str(params.get("attribution") or "").strip()
    theme_key = str(params.get("theme") or "warm")
    theme = sk.PALETTES.get(theme_key, sk.PALETTES["warm"])
    ds_raw = str(params.get("dataset") or "").strip()
    dataset: list[tuple[str, str]] = []
    if ds_raw:
        for pair in ds_raw.replace("，", ",").split(","):
            if ":" in pair or "：" in pair:
                name, _, value = pair.replace("：", ":").partition(":")
                if name.strip() and value.strip():
                    dataset.append((name.strip(), value.strip()))
    if len(quote) > 80:
        print(f"quote-card: 金句 {len(quote)} 字超过 80，只排前 80 字（长的拆多张）", file=sys.stderr)

    svg = render(quote[:80], attribution, theme, dataset)
    out.mkdir(parents=True, exist_ok=True)
    svg_path = out / f"{sk.slugify(quote)}-quote-card.svg"
    svg_path.write_text(svg, encoding="utf-8")
    html_path = out / f"{svg_path.stem}.html"
    html_path.write_text(HTML_TMPL.format(svg=svg_path.name), encoding="utf-8")

    problems = sk.qc_svg(svg)
    qc_md = (
        "## 视觉质检\n\n"
        + ("全部通过：viewBox / 尺寸 / 文字 / 密度。\n" if not problems else "")
        + "\n".join(f"- ⚠️ {p}" for p in problems)
    )
    summary = f"金句卡已生成（{theme_key} 色板" + (f"，数据条 {len(dataset)} 项" if dataset else "") + "）"
    print(f"quote-card: {summary}")
    print(f"quote-card: 已写入 {svg_path.name} / {html_path.name}")
    sk.emit({
        "artifacts": [
            {"path": str(svg_path), "kind": "image", "name": svg_path.name},
            {"path": str(html_path), "kind": "html", "name": html_path.name},
        ],
        "summary": summary,
        "result_markdown": (
            f"{summary}。\n\n- 金句：{len(quote)} 字，排 {len(sk.wrap_cjk(quote, 20))} 行\n"
            f"- 产物：`{svg_path.name}`（SVG 矢量）+ `{html_path.name}`（预览）\n\n{qc_md}"
        ),
        "qc_problems": problems,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
