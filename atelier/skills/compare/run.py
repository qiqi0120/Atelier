#!/usr/bin/env python3
"""compare · A vs B 对比图（F-F11）。"""

from __future__ import annotations

import json
import sys

from atelier.server.visual import svgkit as sk

W, H_HEAD = 1500, 240


def main() -> int:
    params, out, _ = sk.skill_argv(desc="compare")
    left = str(sk.load_params(params, "left", required=True, label="左侧名") or "").strip()
    right = str(sk.load_params(params, "right", required=True, label="右侧名") or "").strip()
    raw = sk.load_params(params, "rows", required=True, label="对比行 JSON")
    rows = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(rows, list) or not rows:
        print('compare: rows 应为 [{"dim":"价格","left":"99","right":"199","win":"left"}] 非空数组', file=sys.stderr)
        return 2
    p = sk.PALETTES.get(str(params.get("theme") or "cool"), sk.PALETTES["cool"])

    row_h = 120
    H = H_HEAD + len(rows) * row_h + 140
    parts = [sk.svg_open(W, H, p["bg"])]
    parts.append(f'<rect x="60" y="40" width="600" height="150" rx="20" fill="{p["bg2"]}"/>')
    parts.append(f'<text x="360" y="130" text-anchor="middle" font-size="52" font-weight="800" fill="{p["fg"]}">{sk.esc(left[:10])}</text>')
    parts.append(f'<rect x="840" y="40" width="600" height="150" rx="20" fill="{p["bg2"]}"/>')
    parts.append(f'<text x="1140" y="130" text-anchor="middle" font-size="52" font-weight="800" fill="{p["fg"]}">{sk.esc(right[:10])}</text>')
    parts.append(f'<text x="750" y="130" text-anchor="middle" font-size="34" fill="{p["sub"]}">VS</text>')
    y = H_HEAD + 30
    for r in rows:
        if not isinstance(r, dict):
            print("compare: rows 项不是对象", file=sys.stderr)
            return 2
        dim = str(r.get("dim", ""))
        lv, rv, win = str(r.get("left", "")), str(r.get("right", "")), str(r.get("win", ""))
        parts.append(f'<text x="750" y="{y+58}" text-anchor="middle" font-size="32" fill="{p["sub"]}">{sk.esc(dim[:10])}</text>')
        for x, val, is_win in ((80, lv, win == "left"), (860, rv, win == "right")):
            if is_win:
                parts.append(f'<rect x="{x}" y="{y+8}" width="560" height="90" rx="14" fill="{p["bg2"]}" stroke="{p["accent"]}" stroke-width="3"/>')
            parts.append(
                f'<text x="{x+280}" y="{y+66}" text-anchor="middle" font-size="38" '
                f'font-weight="{700 if is_win else 500}" fill="{p["accent"] if is_win else p["fg"]}">{sk.esc(val[:16])}</text>'
            )
        y += row_h
    parts.append(f'<text x="{W-70}" y="{H-40}" text-anchor="end" font-size="22" fill="{p["sub"]}">胜出高亮来自你给的 win 标记，脚本不替你判断</text>')
    parts.append(sk.svg_close())
    svg = "".join(parts)

    out.mkdir(parents=True, exist_ok=True)
    svg_path = out / f"{sk.slugify(left)}-vs-{sk.slugify(right)}-compare.svg"
    svg_path.write_text(svg, encoding="utf-8")
    html_path = out / f"{svg_path.stem}.html"
    html_path.write_text(
        f'<!doctype html><meta charset="utf-8"><body style="margin:0;background:#fafaf9;display:grid;place-items:center;min-height:100vh"><img src="{svg_path.name}" style="max-width:94vw;box-shadow:0 10px 40px rgba(0,0,0,.12);border-radius:12px"></body>',
        encoding="utf-8",
    )
    problems = sk.qc_svg(svg)
    wins = sum(1 for r in rows if isinstance(r, dict) and r.get("win") in ("left", "right"))
    print(f"compare: 已生成（{len(rows)} 行，{wins} 行标胜出）")
    sk.emit({
        "artifacts": [
            {"path": str(svg_path), "kind": "image", "name": svg_path.name},
            {"path": str(html_path), "kind": "html", "name": html_path.name},
        ],
        "summary": f"对比图已生成：{left[:10]} vs {right[:10]}（{len(rows)} 行）",
        "result_markdown": (
            f"对比图已生成：{len(rows)} 个维度，其中 {wins} 行标了胜出高亮。结论以你给的 win 标记为准。\n\n"
            "## 视觉质检\n\n" + ("\n".join(f"- ⚠️ {q}" for q in problems) if problems else "全部通过。")
        ),
        "qc_problems": problems,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
