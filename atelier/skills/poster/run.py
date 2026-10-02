#!/usr/bin/env python3
"""poster · 1080×1920 竖版营销海报（F-F8）。"""

from __future__ import annotations

from atelier.server.visual import svgkit as sk

W, H = 1080, 1920


def main() -> int:
    params, out, _ = sk.skill_argv(desc="poster")
    title = str(sk.load_params(params, "title", required=True, label="主标题") or "").strip()
    subtitle = str(params.get("subtitle") or "").strip()
    bullets = [b.strip() for b in str(params.get("bullets") or "").splitlines() if b.strip()]
    cta = str(params.get("cta") or "扫码了解").strip()
    p = sk.PALETTES.get(str(params.get("theme") or "cool"), sk.PALETTES["cool"])

    parts = [sk.svg_open(W, H, p["bg"])]
    parts.append(f'<rect x="0" y="0" width="{W}" height="620" fill="{p["bg2"]}"/>')
    parts.append(f'<circle cx="{W-120}" cy="140" r="220" fill="{p["accent"]}" opacity="0.14"/>')
    # 主标题
    t_lines = sk.wrap_cjk(title, width=7)
    y = 260
    for ln in t_lines[:3]:
        parts.append(
            f'<text x="90" y="{y}" font-size="110" font-weight="800" fill="{p["fg"]}">{sk.esc(ln)}</text>'
        )
        y += 130
    if subtitle:
        for ln in sk.wrap_cjk(subtitle, 16)[:2]:
            parts.append(
                f'<text x="92" y="{y}" font-size="44" fill="{p["sub"]}">{sk.esc(ln)}</text>'
            )
            y += 60
    # 卖点条
    by = 720
    for b in bullets[:6]:
        parts.append(f'<rect x="90" y="{by}" width="900" height="120" rx="20" fill="#FFFFFF" opacity="0.85"/>')
        parts.append(f'<rect x="90" y="{by}" width="16" height="120" rx="8" fill="{p["accent"]}"/>')
        lines = sk.wrap_cjk(b, 24)[:1]
        parts.append(
            f'<text x="140" y="{by+74}" font-size="46" font-weight="600" fill="{p["fg"]}">{sk.esc(lines[0])}</text>'
        )
        by += 150
    # 行动区
    parts.append(f'<rect x="90" y="{H-330}" width="900" height="180" rx="26" fill="{p["accent"]}"/>')
    parts.append(
        f'<text x="{W/2}" y="{H-220}" text-anchor="middle" font-size="64" font-weight="800" fill="#FFFFFF">{sk.esc(cta)}</text>'
    )
    parts.append(sk.svg_close())
    svg = "".join(parts)

    out.mkdir(parents=True, exist_ok=True)
    svg_path = out / f"{sk.slugify(title)}-poster.svg"
    svg_path.write_text(svg, encoding="utf-8")
    html_path = out / f"{svg_path.stem}.html"
    html_path.write_text(
        f'<!doctype html><meta charset="utf-8"><body style="margin:0;background:#fafaf9;display:grid;place-items:center;min-height:100vh"><img src="{svg_path.name}" style="max-height:96vh;border-radius:12px;box-shadow:0 10px 40px rgba(0,0,0,.15)"></body>',
        encoding="utf-8",
    )
    problems = sk.qc_svg(svg)
    truncated = len(t_lines) > 3 or any(len(sk.wrap_cjk(b, 24)) > 1 for b in bullets)
    if truncated:
        problems.append("有文案超版面被截断/压缩，建议缩短标题或卖点")
    print(f"poster: 海报已生成（{p is not None}）")
    print(f"poster: 已写入 {svg_path.name}")
    sk.emit({
        "artifacts": [
            {"path": str(svg_path), "kind": "image", "name": svg_path.name},
            {"path": str(html_path), "kind": "html", "name": html_path.name},
        ],
        "summary": f"海报已生成：{title[:20]}（{len(bullets)} 个卖点）",
        "result_markdown": (
            f"海报已生成：主标题 {len(t_lines)} 行、卖点 {len(bullets)} 条、行动「{cta}」。\n\n"
            "## 视觉质检\n\n" + ("\n".join(f"- ⚠️ {q}" for q in problems) if problems else "全部通过。")
        ),
        "qc_problems": problems,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
