#!/usr/bin/env python3
"""ecommerce-visual · 电商主图版式 ×3 + 详情页视觉方案（F-F14）。"""

from __future__ import annotations

import sys

from atelier.server.visual import svgkit as sk

W, H = 1080, 1080


def card_frame(p: dict, badge: str) -> list[str]:
    return [
        sk.svg_open(W, H, p["bg"]),
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="{p["bg"]}"/>',
        f'<rect x="40" y="40" width="{W-80}" height="{H-80}" rx="28" fill="#FFFFFF" opacity="0.9"/>',
        f'<text x="{W-80}" y="110" text-anchor="end" font-size="28" fill="{p["sub"]}">{sk.esc(badge)}</text>',
    ]


def main() -> int:
    params, out, _ = sk.skill_argv(desc="ecommerce-visual")
    product = str(sk.load_params(params, "product", required=True, label="商品名") or "").strip()
    points = [x.strip() for x in str(params.get("selling_points") or "").splitlines() if x.strip()]
    if len(points) < 2:
        print("ecommerce-visual: 至少给 2 条卖点（每行一条）", file=sys.stderr)
        return 2
    p = sk.PALETTES.get(str(params.get("palette") or "warm"), sk.PALETTES["warm"])
    points = points[:5]

    cards: list[str] = []

    # 版式一：大字报（商品名大字 + 首卖点）
    parts = card_frame(p, "主图 A · 大字报")
    parts.append(f'<text x="{W/2}" y="300" text-anchor="middle" font-size="52" fill="{p["sub"]}">{sk.esc(points[0][:14])}</text>')
    for i, ln in enumerate(sk.wrap_cjk(product, 8)[:3]):
        parts.append(f'<text x="{W/2}" y="{470+i*130}" text-anchor="middle" font-size="120" font-weight="900" fill="{p["fg"]}">{sk.esc(ln)}</text>')
    parts.append(f'<rect x="{W/2-280}" y="840" width="560" height="110" rx="55" fill="{p["accent"]}"/>')
    parts.append(f'<text x="{W/2}" y="912" text-anchor="middle" font-size="46" font-weight="700" fill="#FFFFFF">{sk.esc(points[1][:12])}</text>')
    parts.append(sk.svg_close())
    cards.append("".join(parts))

    # 版式二：卖点矩阵（2×2）
    parts = card_frame(p, "主图 B · 卖点矩阵")
    parts.append(f'<text x="{W/2}" y="230" text-anchor="middle" font-size="72" font-weight="800" fill="{p["fg"]}">{sk.esc(product[:12])}</text>')
    for i, pt in enumerate(points[:4]):
        cx = 330 if i % 2 == 0 else 750
        cy = 480 if i < 2 else 760
        parts.append(f'<rect x="{cx-230}" y="{cy-90}" width="460" height="180" rx="18" fill="{p["bg2"]}"/>')
        lines = sk.wrap_cjk(pt, 12)[:2]
        ty = cy - (10 if len(lines) > 1 else 0)
        for ln in lines:
            parts.append(f'<text x="{cx}" y="{ty}" text-anchor="middle" font-size="40" font-weight="600" fill="{p["fg"]}">{sk.esc(ln)}</text>')
            ty += 52
    parts.append(sk.svg_close())
    cards.append("".join(parts))

    # 版式三：锚点对比（价格锚 + 权益行）
    parts = card_frame(p, "主图 C · 锚点")
    parts.append(f'<text x="{W/2}" y="240" text-anchor="middle" font-size="64" font-weight="800" fill="{p["fg"]}">{sk.esc(product[:12])}</text>')
    parts.append(f'<rect x="{W/2-320}" y="300" width="640" height="150" rx="20" fill="{p["bg2"]}"/>')
    parts.append(f'<text x="{W/2}" y="395" text-anchor="middle" font-size="76" font-weight="900" fill="{p["accent"]}">{sk.esc(points[0][:14])}</text>')
    yy = 560
    for pt in points[1:4]:
        parts.append(f'<circle cx="{W/2-260}" cy="{yy-12}" r="10" fill="{p["accent"]}"/>')
        parts.append(f'<text x="{W/2-220}" y="{yy}" font-size="40" fill="{p["fg"]}">{sk.esc(pt[:16])}</text>')
        yy += 100
    parts.append(sk.svg_close())
    cards.append("".join(parts))

    out.mkdir(parents=True, exist_ok=True)
    arts = []
    for idx, svg in enumerate(cards):
        svg_path = out / f"{sk.slugify(product)}-main-{idx+1}.svg"
        svg_path.write_text(svg, encoding="utf-8")
        arts.append({"path": str(svg_path), "kind": "image", "name": svg_path.name})
    plan = out / f"{sk.slugify(product)}-detail-plan.md"
    plan.write_text(
        f"# {product} · 详情页视觉方案\n\n"
        f"## 色板\n\n{' / '.join(f'{k}={v}' for k, v in p.items())}\n\n"
        "## 版式分工\n\n"
        "- 主图 A（大字报）：信息流第一眼，商品名为主，配首卖点副标\n"
        "- 主图 B（卖点矩阵）：详情页第 2 屏，2×2 铺核心卖点\n"
        "- 主图 C（锚点）：转化位，首卖点做大字锚 + 权益清单\n\n"
        "## 详情页节奏建议\n\n"
        f"1. 首屏主图 A → 2. 痛点场景（配实拍）→ 3. 卖点矩阵 B → 4. 细节实拍 ×3 → 5. 锚点 C + 规格 → 6. 售后保障\n\n"
        "## 待补的实拍位\n\n"
        + "\n".join(f"- 实拍 {i+1}：{pt[:16]} 场景" for i, pt in enumerate(points))
        + "\n\n（本方案只做版式与节奏，实拍图请在设计工具里替换占位）\n",
        encoding="utf-8",
    )
    arts.append({"path": str(plan), "kind": "markdown", "name": plan.name})
    problems = sk.qc_svg(cards[0])
    print("ecommerce-visual: 3 张主图 + 方案已生成")
    sk.emit({
        "artifacts": arts,
        "summary": f"电商主图 ×3 + 详情方案（{len(points)} 卖点）",
        "result_markdown": (
            "已生成 3 张主图版式（大字报 / 卖点矩阵 / 锚点）+ 详情页视觉方案。SVG 交付，"
            "实拍占位在设计工具里替换。\n\n## 视觉质检\n\n"
            + ("\n".join(f"- ⚠️ {q}" for q in problems) if problems else "全部通过。")
        ),
        "qc_problems": problems,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
