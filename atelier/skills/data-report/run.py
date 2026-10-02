#!/usr/bin/env python3
"""data-report · CSV/JSON → 统计 + SVG 图 + 报告页（F-F49，确定性统计）。"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

from atelier.server.visual import svgkit as sk

SERIES_COLORS = ["#059669", "#1D4ED8", "#E8590C"]


def load_rows(raw: str) -> list[dict]:
    raw = raw.strip()
    if not raw:
        raise ValueError("数据为空")
    # 文件路径
    p = Path(raw.splitlines()[0].strip())
    if p.exists() and p.suffix.lower() in {".csv", ".json"}:
        raw = p.read_text(encoding="utf-8")
    rows: list[dict] = []
    if raw.startswith(("[", "{")):
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        for item in data:
            if isinstance(item, dict):
                rows.append({k: v for k, v in item.items()})
    else:
        reader = csv.DictReader(io.StringIO(raw))
        for row in reader:
            rows.append(dict(row))
    if not rows:
        raise ValueError("没有解析到数据行")
    return rows


def is_number(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def col_stats(rows: list[dict], col: str) -> dict:
    vals = [float(r[col]) for r in rows if is_number(r.get(col))]
    if not vals:
        return {}
    vals_sorted = sorted(vals)
    n = len(vals)
    return {
        "count": n,
        "sum": sum(vals),
        "mean": sum(vals) / n,
        "min": vals_sorted[0],
        "max": vals_sorted[-1],
        "median": vals_sorted[n // 2] if n % 2 else (vals_sorted[n // 2 - 1] + vals_sorted[n // 2]) / 2,
    }


def bar_svg(labels: list[str], values: list[float], title: str) -> str:
    W, H = 1200, 560
    p = sk.PALETTES["cool"]
    parts = [sk.svg_open(W, H, p["bg"])]
    mx = max(values) or 1.0
    plot_x, plot_y, plot_w, plot_h = 120, 90, W - 220, H - 180
    parts.append(f'<line x1="{plot_x}" y1="{plot_y+plot_h}" x2="{plot_x+plot_w}" y2="{plot_y+plot_h}" stroke="{p["line"]}" stroke-width="2"/>')
    n = len(values)
    step = plot_w / n
    for i, (label, v) in enumerate(zip(labels, values)):
        hgt = (v / mx) * plot_h
        bw = min(80, step * 0.6)
        cx = plot_x + step * i + step / 2
        parts.append(f'<rect x="{cx-bw/2:.0f}" y="{plot_y+plot_h-hgt:.0f}" width="{bw:.0f}" height="{hgt:.0f}" rx="6" fill="{SERIES_COLORS[i % 3]}"/>')
        parts.append(f'<text x="{cx:.0f}" y="{plot_y+plot_h+28}" text-anchor="middle" font-size="20" fill="{p["sub"]}">{sk.esc(label[:8])}</text>')
        parts.append(f'<text x="{cx:.0f}" y="{plot_y+plot_h-hgt-8:.0f}" text-anchor="middle" font-size="22" fill="{p["fg"]}">{v:g}</text>')
    parts.append(f'<text x="{W/2}" y="50" text-anchor="middle" font-size="30" font-weight="700" fill="{p["fg"]}">{sk.esc(title[:30])}</text>')
    parts.append(sk.svg_close())
    return "".join(parts)


def main() -> int:
    params, out, _ = sk.skill_argv(desc="data-report")
    raw = str(sk.load_params(params, "data", required=True, label="数据 CSV/JSON") or "")
    title = str(params.get("title") or "").strip() or "数据报告"
    try:
        rows = load_rows(raw)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"data-report: 数据解析失败（{e}）。支持 CSV 文本/路径、JSON 对象数组", file=sys.stderr)
        return 2

    cols = list(rows[0].keys())
    num_cols = [c for c in cols if sum(1 for r in rows if is_number(r.get(c))) >= max(1, len(rows) // 2)]
    text_cols = [c for c in cols if c not in num_cols]

    lines = [f"# {title}", "", f"> 数据 {len(rows)} 行 × {len(cols)} 列 · 统计由脚本计算（确定性），AI 只在对话里解读这些数字。", ""]
    for c in num_cols:
        s = col_stats(rows, c)
        if not s:
            continue
        lines += [
            f"## {c}", "",
            f"- 条数 {s['count']} · 合计 {s['sum']:.4g} · 均值 {s['mean']:.4g} · 中位 {s['median']:.4g}",
            f"- 最小 {s['min']:.4g} · 最大 {s['max']:.4g}",
            "",
        ]
    freq_lines = []
    for c in text_cols[:3]:
        from collections import Counter

        counter = Counter(str(r.get(c, "")) for r in rows)
        top = counter.most_common(3)
        freq_lines.append(f"- {c}：Top3 = " + "、".join(f"{k or '(空)'}×{v}" for k, v in top))
    if freq_lines:
        lines += ["## 文本列频次", "", *freq_lines, ""]

    out.mkdir(parents=True, exist_ok=True)
    arts: list[dict] = []
    for i, c in enumerate(num_cols[:3]):
        labels = [str(r.get(c == cols[0] and cols[0] or cols[0], i + 1))[:8] for r in rows]
        # x 轴用第一列当标签；数值取该列
        labels = [str(r.get(cols[0], i + 1))[:8] for i, r in enumerate(rows)]
        values = [float(r[c]) for r in rows if is_number(r.get(c))]
        svg = bar_svg(labels[:len(values)], values, f"{c} 分布")
        svg_path = out / f"report-chart-{i+1}-{sk.slugify(c)}.svg"
        svg_path.write_text(svg, encoding="utf-8")
        arts.append({"path": str(svg_path), "kind": "image", "name": svg_path.name})
        lines.append(f"![{c}]({svg_path.name})")
        lines.append("")
    lines += ["## 洞察", "", "（本技能只做确定性统计；把上面的数字丢进对话让 AI 基于真实统计解读——它不参与算数。）", ""]

    dst = out / f"{sk.slugify(title)}-report.md"
    dst.write_text("\n".join(lines), encoding="utf-8")
    arts.insert(0, {"path": str(dst), "kind": "markdown", "name": dst.name})
    print(f"data-report: {len(rows)} 行 · 数值列 {len(num_cols)} · 图 {min(3, len(num_cols))} 张")
    sk.emit({
        "artifacts": arts,
        "summary": f"报告完成：{len(rows)} 行 × {len(cols)} 列",
        "result_markdown": (
            f"数据报告完成：{len(rows)} 行，数值列 {num_cols or '无'}，文本列频次 {len(freq_lines)} 条，"
            f"图表 {min(3, len(num_cols))} 张。统计是脚本算的；洞察段留白，建议接对话让 AI 解读真实数字。"
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
