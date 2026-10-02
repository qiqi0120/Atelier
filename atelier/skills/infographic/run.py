#!/usr/bin/env python3
"""infographic · 竖版信息长图（F-F10，静态；GIF 如实降级为说明）。"""

from __future__ import annotations

import json
import sys

from atelier.server.visual import svgkit as sk

W = 1080


def main() -> int:
    params, out, _ = sk.skill_argv(desc="infographic")
    title = str(sk.load_params(params, "title", required=True, label="大标题") or "").strip()
    raw = sk.load_params(params, "sections", required=True, label="分节 JSON")
    sections = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(sections, list) or not sections:
        print('infographic: sections 应为 [{"heading":"..","points":[".."],"metric":".."}] 非空数组', file=sys.stderr)
        return 2
    p = sk.PALETTES.get(str(params.get("theme") or "fresh"), sk.PALETTES["fresh"])

    parts = [sk.svg_open(W, 100, p["bg"])]
    y = 150
    parts.append(f'<rect x="0" y="0" width="{W}" height="230" fill="{p["bg2"]}"/>')
    for ln in sk.wrap_cjk(title, 16)[:2]:
        parts.append(f'<text x="70" y="{y}" font-size="62" font-weight="800" fill="{p["fg"]}">{sk.esc(ln)}</text>')
        y += 76
    y = 300
    for i, sec in enumerate(sections, 1):
        if not isinstance(sec, dict):
            print(f"infographic: 第 {i} 节不是对象", file=sys.stderr)
            return 2
        heading = str(sec.get("heading", f"第 {i} 节"))
        points = [str(x) for x in (sec.get("points") or [])][:5]
        metric = str(sec.get("metric") or "")
        sec_h = 90 + len(points) * 58 + (110 if metric else 0) + 40
        parts.append(f'<rect x="60" y="{y}" width="{W-120}" height="{sec_h-24}" rx="20" fill="#FFFFFF" opacity="0.92"/>')
        parts.append(f'<circle cx="120" cy="{y+58}" r="30" fill="{p["accent"]}"/>')
        parts.append(f'<text x="120" y="{y+70}" text-anchor="middle" font-size="34" font-weight="800" fill="#FFFFFF">{i}</text>')
        parts.append(f'<text x="170" y="{y+70}" font-size="40" font-weight="700" fill="{p["fg"]}">{sk.esc(heading[:20])}</text>')
        py = y + 140
        for pt in points:
            parts.append(f'<circle cx="110" cy="{py-10}" r="6" fill="{p["accent"]}"/>')
            for ln in sk.wrap_cjk(pt, 34)[:2]:
                parts.append(f'<text x="132" y="{py}" font-size="30" fill="{p["fg"]}">{sk.esc(ln)}</text>')
                py += 44
            py += 14
        if metric:
            parts.append(f'<rect x="100" y="{py}" width="{W-240}" height="92" rx="14" fill="{p["bg2"]}"/>')
            parts.append(f'<text x="{W/2}" y="{py+60}" text-anchor="middle" font-size="42" font-weight="800" fill="{p["accent"]}">{sk.esc(metric[:24])}</text>')
            py += 110
        y += sec_h
    parts.append(f'<text x="{W-70}" y="{y+10}" text-anchor="end" font-size="24" fill="{p["sub"]}">Atelier · 信息图（静态）</text>')
    parts.append("</svg>")
    # 修正画布高度
    svg = "".join(parts).replace('viewBox="0 0 1080 100"', f'viewBox="0 0 {W} {y+60}"', 1)
    svg = svg.replace('width="1080" height="100"', f'width="{W}" height="{y+60}"', 1)

    out.mkdir(parents=True, exist_ok=True)
    svg_path = out / f"{sk.slugify(title)}-infographic.svg"
    svg_path.write_text(svg, encoding="utf-8")
    html_path = out / f"{svg_path.stem}.html"
    html_path.write_text(
        f'<!doctype html><meta charset="utf-8"><body style="margin:0;background:#fafaf9;display:grid;place-items:center;min-height:100vh"><img src="{svg_path.name}" style="max-height:96vh;box-shadow:0 10px 40px rgba(0,0,0,.12);border-radius:12px"></body>',
        encoding="utf-8",
    )
    problems = sk.qc_svg(svg)
    print(f"infographic: 已生成（{len(sections)} 节，高 {y+60}px）")
    sk.emit({
        "artifacts": [
            {"path": str(svg_path), "kind": "image", "name": svg_path.name},
            {"path": str(html_path), "kind": "html", "name": html_path.name},
        ],
        "summary": f"信息图已生成（{len(sections)} 节）",
        "result_markdown": (
            f"信息图已生成：{len(sections)} 节，画布 1080×{y+60}。静态长图；动效请拆帧在视频工具里做。\n\n"
            "## 视觉质检\n\n" + ("\n".join(f"- ⚠️ {q}" for q in problems) if problems else "全部通过。")
        ),
        "qc_problems": problems,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
