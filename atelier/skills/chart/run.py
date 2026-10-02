#!/usr/bin/env python3
"""chart · 数据 → SVG 图表（F-F9）。9 类，统计确定性（AI 不参与数值）。"""

from __future__ import annotations

import json
import math
import sys

from atelier.server.visual import svgkit as sk

W, H = 1600, 1000
TYPES = ("bar", "hbar", "line", "area", "pie", "donut", "scatter", "radar", "funnel")
SERIES_COLORS = ["#059669", "#1D4ED8", "#E8590C", "#7C3AED", "#B45309", "#0E7490", "#BE185D", "#4D7C0F"]


def norm_series(raw: str | dict | list) -> list[tuple[str, float]]:
    # skill_argv 已把 --params 解析成对象；字符串（嵌套 JSON）兜底再 parse 一次
    data = json.loads(raw) if isinstance(raw, str) else raw
    out: list[tuple[str, float]] = []
    if isinstance(data, dict):
        for k, v in data.items():
            out.append((str(k), float(v)))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                out.append((str(item.get("name", item.get("label", "?"))), float(item.get("value", 0))))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                out.append((str(item[0]), float(item[1])))
    if not out:
        raise ValueError("series 解析为空")
    return out


def axis_frame(parts: list[str], p: dict, px: float, py: float, pw: float, ph: float) -> None:
    parts.append(f'<line x1="{px}" y1="{py+ph}" x2="{px+pw}" y2="{py+ph}" stroke="{p["line"]}" stroke-width="2"/>')
    parts.append(f'<line x1="{px}" y1="{py}" x2="{px}" y2="{py+ph}" stroke="{p["line"]}" stroke-width="2"/>')


def main() -> int:
    params, out, _ = sk.skill_argv(desc="chart")
    ctype = str(params.get("type") or "bar")
    if ctype not in TYPES:
        print(f"chart: type 非法 {ctype!r}，可选 {list(TYPES)}", file=sys.stderr)
        return 2
    raw = sk.load_params(params, "series", required=True, label="数据 JSON")
    try:
        data = norm_series(raw)
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as e:
        print(f'chart: series 不是合法数据（{e}）。示例：{{"周一":12,"周二":18}}', file=sys.stderr)
        return 2
    title = str(params.get("title") or "").strip()
    p = sk.PALETTES.get(str(params.get("theme") or "cool"), sk.PALETTES["cool"])

    parts = [sk.svg_open(W, H, p["bg"])]
    top = 90
    if title:
        parts.append(
            f'<text x="{W/2}" y="70" text-anchor="middle" font-size="44" font-weight="700" '
            f'fill="{p["fg"]}">{sk.esc(title)}</text>'
        )
        top = 130
    n = len(data)
    mx = max(v for _, v in data) or 1.0
    mn = min(v for _, v in data)
    px, py, pw, ph = 160, top + 40, W - 320, H - top - 220
    cx = W / 2

    if ctype in ("bar", "line", "area", "scatter"):
        axis_frame(parts, p, px, py, pw, ph)
        step = pw / n
        for i, (name, v) in enumerate(data):
            cxx = px + step * i + step / 2
            hgt = (v / mx) * ph
            color = SERIES_COLORS[i % len(SERIES_COLORS)]
            if ctype == "bar":
                bw = min(90, step * 0.6)
                parts.append(f'<rect x="{cxx-bw/2:.0f}" y="{py+ph-hgt:.0f}" width="{bw:.0f}" height="{hgt:.0f}" rx="8" fill="{color}"/>')
            elif ctype == "scatter":
                r = 8 + 18 * (v / mx)
                parts.append(f'<circle cx="{cxx:.0f}" cy="{py+ph-hgt:.0f}" r="{r:.0f}" fill="{color}" opacity="0.75"/>')
            if ctype in ("bar", "scatter"):
                parts.append(f'<text x="{cxx:.0f}" y="{py+ph+34}" text-anchor="middle" font-size="24" fill="{p["sub"]}">{sk.esc(name[:6])}</text>')
                parts.append(f'<text x="{cxx:.0f}" y="{py+ph-hgt-12:.0f}" text-anchor="middle" font-size="26" fill="{p["fg"]}">{v:g}</text>')
        if ctype in ("line", "area"):
            pts = [f"{px + step*i + step/2:.0f},{py+ph-(v/mx)*ph:.0f}" for i, (_, v) in enumerate(data)]
            if ctype == "area":
                parts.append(f'<polygon points="{px},{py+ph} {" ".join(pts)} {px+pw},{py+ph}" fill="{SERIES_COLORS[0]}" opacity="0.22"/>')
            parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{SERIES_COLORS[0]}" stroke-width="5" stroke-linejoin="round"/>')
            for i, (name, _v) in enumerate(data):
                pxx, pyy = pts[i].split(",")
                parts.append(f'<circle cx="{pxx}" cy="{pyy}" r="7" fill="{SERIES_COLORS[0]}"/>')
                parts.append(f'<text x="{pxx}" y="{py+ph+34}" text-anchor="middle" font-size="24" fill="{p["sub"]}">{sk.esc(name[:6])}</text>')
    elif ctype == "hbar":
        bh = min(64, (ph - 30 * n) / n)
        for i, (name, v) in enumerate(data):
            yy = py + i * (bh + 30)
            bw = (v / mx) * pw
            parts.append(f'<rect x="{px}" y="{yy:.0f}" width="{bw:.0f}" height="{bh:.0f}" rx="10" fill="{SERIES_COLORS[i % len(SERIES_COLORS)]}"/>')
            parts.append(f'<text x="{px-14}" y="{yy+bh*0.7:.0f}" text-anchor="end" font-size="26" fill="{p["sub"]}">{sk.esc(name[:8])}</text>')
            parts.append(f'<text x="{px+bw+12:.0f}" y="{yy+bh*0.7:.0f}" font-size="26" fill="{p["fg"]}">{v:g}</text>')
    elif ctype in ("pie", "donut"):
        total = sum(v for _, v in data) or 1.0
        ccx, cy, r = W / 2, (top + 40 + H) / 2 - 60, min(ph, pw) / 2 - 60
        acc = -math.pi / 2
        for i, (name, v) in enumerate(data):
            frac = v / total
            a2 = acc + frac * 2 * math.pi
            x1, y1 = ccx + r * math.cos(acc), cy + r * math.sin(acc)
            x2, y2 = ccx + r * math.cos(a2), cy + r * math.sin(a2)
            large = 1 if frac > 0.5 else 0
            color = SERIES_COLORS[i % len(SERIES_COLORS)]
            if ctype == "pie":
                parts.append(f'<path d="M{ccx},{cy} L{x1:.1f},{y1:.1f} A{r},{r} 0 {large} 1 {x2:.1f},{y2:.1f} Z" fill="{color}" stroke="#FFFFFF" stroke-width="3"/>')
            else:
                ri = r * 0.55
                xi1, yi1 = ccx + ri * math.cos(acc), cy + ri * math.sin(acc)
                xi2, yi2 = ccx + ri * math.cos(a2), cy + ri * math.sin(a2)
                parts.append(
                    f'<path d="M{x1:.1f},{y1:.1f} A{r},{r} 0 {large} 1 {x2:.1f},{y2:.1f} '
                    f'L{xi2:.1f},{yi2:.1f} A{ri},{ri} 0 {large} 0 {xi1:.1f},{yi1:.1f} Z" '
                    f'fill="{color}" stroke="#FFFFFF" stroke-width="3"/>'
                )
            lx = ccx + (r + 46) * math.cos((acc + a2) / 2)
            ly = cy + (r + 46) * math.sin((acc + a2) / 2)
            parts.append(f'<text x="{lx:.0f}" y="{ly:.0f}" text-anchor="middle" font-size="26" fill="{p["fg"]}">{sk.esc(name[:6])} {v:g}</text>')
            acc = a2
    elif ctype == "radar":
        labels = [str(x) for x in (params.get("labels") if isinstance(params.get("labels"), list) else [])]
        vals = [v for _, v in data]
        axes = len(labels) or len(vals)
        if axes < 3:
            print("chart: radar 至少需要 3 个维度（labels 或 series 项 ≥3）", file=sys.stderr)
            return 2
        vals = (vals + [0] * axes)[:axes]
        vmax = max(vals + [1])
        ccx, cy, r = W / 2, (top + 40 + H) / 2 - 40, min(ph, pw) / 2 - 90
        for a in range(axes):
            ang = -math.pi / 2 + a * 2 * math.pi / axes
            gx, gy = ccx + r * math.cos(ang), cy + r * math.sin(ang)
            parts.append(f'<line x1="{ccx}" y1="{cy}" x2="{gx:.0f}" y2="{gy:.0f}" stroke="{p["line"]}"/>')
            lx, ly = ccx + (r + 34) * math.cos(ang), cy + (r + 34) * math.sin(ang)
            label = labels[a] if a < len(labels) else data[a][0]
            parts.append(f'<text x="{lx:.0f}" y="{ly:.0f}" text-anchor="middle" font-size="26" fill="{p["sub"]}">{sk.esc(str(label)[:6])}</text>')
        poly = []
        for a, v in enumerate(vals):
            ang = -math.pi / 2 + a * 2 * math.pi / axes
            rr = (v / vmax) * r
            poly.append(f"{ccx+rr*math.cos(ang):.0f},{cy+rr*math.sin(ang):.0f}")
        parts.append(f'<polygon points="{" ".join(poly)}" fill="{SERIES_COLORS[0]}" opacity="0.35" stroke="{SERIES_COLORS[0]}" stroke-width="4"/>')
    else:  # funnel
        row_h = ph / n
        for i, (name, v) in enumerate(data):
            yy = py + i * row_h
            hh = row_h - 24
            wtop = pw * (1 - i * 0.7 / n)
            wbot = pw * (1 - (i + 1) * 0.7 / n)
            color = SERIES_COLORS[i % len(SERIES_COLORS)]
            parts.append(
                f'<polygon points="{cx-wtop/2:.0f},{yy:.0f} {cx+wtop/2:.0f},{yy:.0f} '
                f'{cx+wbot/2:.0f},{yy+hh:.0f} {cx-wbot/2:.0f},{yy+hh:.0f}" fill="{color}" opacity="0.9"/>'
            )
            parts.append(f'<text x="{cx}" y="{yy+hh/2+10:.0f}" text-anchor="middle" font-size="28" font-weight="600" fill="#FFFFFF">{sk.esc(name[:8])} {v:g}</text>')

    parts.append(
        f'<text x="{W-100}" y="{H-40}" text-anchor="end" font-size="22" fill="{p["sub"]}">'
        f'n={n} · max={mx:g}{"" if mn == 0 else f" · min={mn:g}"}</text>'
    )
    parts.append(sk.svg_close())
    svg = "".join(parts)

    out.mkdir(parents=True, exist_ok=True)
    svg_path = out / f"{ctype}-{sk.slugify(title or str(n))}-chart.svg"
    svg_path.write_text(svg, encoding="utf-8")
    html_path = out / f"{svg_path.stem}.html"
    html_path.write_text(
        f'<!doctype html><meta charset="utf-8"><body style="margin:0;background:#fafaf9;display:grid;place-items:center;min-height:100vh"><img src="{svg_path.name}" style="max-width:94vw;box-shadow:0 10px 40px rgba(0,0,0,.12);border-radius:12px"></body>',
        encoding="utf-8",
    )
    problems = sk.qc_svg(svg)
    print(f"chart: {ctype} 已生成（{n} 项数据）")
    print(f"chart: 已写入 {svg_path.name}")
    sk.emit({
        "artifacts": [
            {"path": str(svg_path), "kind": "image", "name": svg_path.name},
            {"path": str(html_path), "kind": "html", "name": html_path.name},
        ],
        "summary": f"{ctype} 图已生成（{n} 项）",
        "result_markdown": (
            f"{ctype} 图已生成：{n} 项数据，max={mx:g}" + (f"，min={mn:g}" if mn else "") +
            "。统计由脚本从输入数据计算，AI 不参与数值。\n\n"
            "## 视觉质检\n\n" + ("\n".join(f"- ⚠️ {q}" for q in problems) if problems else "全部通过。")
        ),
        "qc_problems": problems,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
