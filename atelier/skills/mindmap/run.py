#!/usr/bin/env python3
"""mindmap · 缩进大纲 → SVG 导图 + 可折叠 HTML（F-F12）。"""

from __future__ import annotations

import sys

from atelier.server.visual import svgkit as sk

NODE_W, NODE_H, GAP_X, GAP_Y = 200, 64, 90, 26


def parse_outline(text: str) -> tuple[str, list[tuple[int, str]]]:
    """解析缩进大纲 → (root, [(depth, label)])。depth 从 1 起，>4 并入 4。"""
    root = ""
    nodes: list[tuple[int, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        indent = (len(line) - len(line.lstrip(" "))) // 2
        label = line.strip()
        if not root:
            root = label
            continue
        nodes.append((min(indent + 1, 4), label))
    return root, nodes


def layout(nodes: list[tuple[int, str]]) -> tuple[list[dict], float, float]:
    """简单树布局：先按叶子序排 y（后序），父节点 y = 子节点均值。"""
    placed: list[dict] = []
    y = 0.0
    for depth, label in nodes:
        y += NODE_H + GAP_Y
        placed.append({"depth": depth, "label": label, "x": 80 + depth * (NODE_W + GAP_X), "y": y})
    # 非叶节点上移到它第一个孩子的 y（读起来是标准的树形）
    for i, n in enumerate(placed):
        child = next((m for m in placed[i + 1:] if m["depth"] == n["depth"] + 1), None)
        if child is not None:
            n["y"] = child["y"]
    return placed, 80, y + NODE_H


def render(root: str, placed: list[dict], height: float, p: dict) -> str:
    W = int(200 + max((n["x"] for n in placed), default=0) + NODE_W)
    H = int(height)
    parts = [sk.svg_open(W, H, p["bg"])]
    # 根节点
    parts.append(f'<rect x="40" y="40" width="30" height="70" rx="12" fill="{p["accent"]}"/>')
    parts.append(f'<text x="90" y="90" font-size="44" font-weight="800" fill="{p["fg"]}">{sk.esc(root[:16])}</text>')
    root_right = 90 + len(root[:16]) * 44 + 30
    # 连线先画（压在节点下层）：每个节点连到它之前最近的 depth-1 节点
    prev_by_depth: dict[int, dict] = {}
    for n in placed:
        parent = prev_by_depth.get(n["depth"] - 1)
        x1 = root_right if parent is None else parent["x"] + NODE_W
        y1 = 75 if parent is None else parent["y"] + NODE_H / 2
        parts.append(
            f'<path d="M{x1},{y1} C{x1+40},{y1} {n["x"]-50},{n["y"]+NODE_H/2} {n["x"]-8},{n["y"]+NODE_H/2}" '
            f'fill="none" stroke="{p["line"]}" stroke-width="3"/>'
        )
        prev_by_depth[n["depth"]] = n
    # 节点
    for n in placed:
        fill = p["bg2"] if n["depth"] == 1 else "#FFFFFF"
        stroke = p["accent"] if n["depth"] == 1 else p["line"]
        parts.append(
            f'<rect x="{n["x"]}" y="{n["y"]}" width="{NODE_W}" height="{NODE_H}" rx="14" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{2 if n["depth"] == 1 else 1.5}"/>'
        )
        lines = sk.wrap_cjk(n["label"], 9)[:2]
        ty = n["y"] + (NODE_H / 2 + 6 if len(lines) == 1 else 26)
        for ln in lines:
            parts.append(
                f'<text x="{n["x"]+16}" y="{ty}" font-size="{24 if n["depth"] > 1 else 28}" fill="{p["fg"]}">{sk.esc(ln)}</text>'
            )
            ty += 30
    parts.append(sk.svg_close())
    return "".join(parts)


HTML_TMPL = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>思维导图（可折叠）</title>
<style>
body{{font-family:PingFang SC,sans-serif;background:#FAFAF9;padding:28px;line-height:1.6}}
details{{margin:6px 0 6px 22px;padding-left:12px;border-left:3px solid #10b981}}
summary{{cursor:pointer;font-size:15px;font-weight:600;padding:4px 8px;border-radius:8px;background:#fff;border:1px solid #e7e5e4;display:inline-block}}
.depth1>summary{{background:#D1FAE5;border-color:#10b981}}
</style></head><body>
<h2>{root}</h2>
{body}
<p style="color:#999;font-size:12px">点击节点折叠/展开 · 矢量版见同名 .svg</p>
</body></html>"""


def to_html_tree(root: str, nodes: list[tuple[int, str]]) -> str:
    parts = []
    stack: list[int] = []
    for depth, label in nodes:
        while stack and stack[-1] >= depth:
            stack.pop()
            parts.append("</details>")
        cls = ' class="depth1"' if depth == 1 else ""
        parts.append(f"<details{cls}><summary>{sk.esc(label)}</summary>")
        stack.append(depth)
    while stack:
        stack.pop()
        parts.append("</details>")
    return "\n".join(parts)


def main() -> int:
    params, out, _ = sk.skill_argv(desc="mindmap")
    outline = str(sk.load_params(params, "outline", required=True, label="缩进大纲") or "")
    root, nodes = parse_outline(outline)
    if not root or not nodes:
        print("mindmap: 大纲至少要 1 行根节点 + 1 行子节点（两空格缩进分层）", file=sys.stderr)
        return 2
    deep = [n for n in nodes if n[0] == 4 and "    " in outline.split(n[1])[0].splitlines()[-1]]
    p = sk.PALETTES.get(str(params.get("theme") or "warm"), sk.PALETTES["warm"])
    placed, _x, height = layout(nodes)
    svg = render(root, placed, height + 60, p)

    out.mkdir(parents=True, exist_ok=True)
    svg_path = out / f"{sk.slugify(root)}-mindmap.svg"
    svg_path.write_text(svg, encoding="utf-8")
    html_path = out / f"{svg_path.stem}.html"
    html_path.write_text(HTML_TMPL.format(root=sk.esc(root), body=to_html_tree(root, nodes)), encoding="utf-8")
    problems = sk.qc_svg(svg)
    if deep:
        problems.append("有超过 4 层的节点已并入第 4 层")
    print(f"mindmap: 已生成（根「{root[:12]}」，{len(nodes)} 节点）")
    sk.emit({
        "artifacts": [
            {"path": str(svg_path), "kind": "image", "name": svg_path.name},
            {"path": str(html_path), "kind": "html", "name": html_path.name},
        ],
        "summary": f"思维导图已生成（{len(nodes)} 节点）",
        "result_markdown": (
            f"思维导图已生成：根「{root[:16]}」，{len(nodes)} 个节点，SVG + 可折叠 HTML 两版。\n\n"
            "## 视觉质检\n\n" + ("\n".join(f"- ⚠️ {q}" for q in problems) if problems else "全部通过。")
        ),
        "qc_problems": problems,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
