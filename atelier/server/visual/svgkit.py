"""视觉技能共享 SVG 工具（SPEC-13 §2）。

技能 run.py 通过 ``from atelier.server.visual import svgkit`` 复用；runner 以
``sys.executable`` 在包环境内执行脚本，import 合法。这里只放**确定性**原语：
转义、头尾、CJK 换行、色板、slug、结构质检、结果回传——观点段留给 agent。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.sax import saxutils

__all__ = [
    "PALETTES",
    "esc",
    "qc_svg",
    "slugify",
    "svg_close",
    "svg_open",
    "wrap_cjk",
]

#: 三套安全色板（浅底深字，避开纯黑大面积；SPEC-13 §0 D6）
PALETTES: dict[str, dict[str, str]] = {
    "warm": {"bg": "#FFF7ED", "bg2": "#FFE8D6", "fg": "#3B2F2F", "accent": "#E8590C", "sub": "#8A6E5F", "line": "#F1D9C4"},
    "cool": {"bg": "#F1F5F9", "bg2": "#DBEAFE", "fg": "#1F2937", "accent": "#1D4ED8", "sub": "#5B6B7F", "line": "#CBD5E1"},
    "fresh": {"bg": "#F0FDF4", "bg2": "#D1FAE5", "fg": "#143D2B", "accent": "#059669", "sub": "#5F7F70", "line": "#BBE5CD"},
    "ink": {"bg": "#FAFAF9", "bg2": "#E7E5E4", "fg": "#292524", "accent": "#57534E", "sub": "#78716C", "line": "#D6D3D1"},
}


def esc(text: str) -> str:
    """XML 文本转义（含引号，属性位安全）。"""
    return saxutils.escape(str(text), {'"': "&quot;"})


def svg_open(width: int, height: int, bg: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{bg}"/>'
    )


def svg_close() -> str:
    return "</svg>"


def wrap_cjk(text: str, width: int) -> list[str]:
    """按显示宽度断行：CJK 字符算 1、ASCII 算 0.55，逐字贪心。

    确定性排版用——不追求排版学最优，只保证不溢出画布。
    """
    lines: list[str] = []
    cur = ""
    cur_w = 0.0
    for ch in str(text):
        w = 1.0 if ord(ch) > 0x2E80 else 0.55
        if cur_w + w > width and cur:
            lines.append(cur)
            cur, cur_w = "", 0.0
        cur += ch
        cur_w += w
    if cur:
        lines.append(cur)
    return lines or [""]


def slugify(text: str, limit: int = 24) -> str:
    s = "".join(c.lower() if c.isascii() and c.isalnum() else "-" for c in text[:limit]).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s or "visual"


def qc_svg(svg: str, *, min_elements: int = 4) -> list[str]:
    """SVG 结构质检（SPEC-13 §0 D3）：返回问题列表，空列表 = 过。

    检查：有 viewBox、尺寸不小于 200px、含文本元素、无大面积纯黑、元素密度达标。
    """
    problems: list[str] = []
    if "<svg" not in svg:
        return ["内容不是 SVG"]
    if "viewBox" not in svg:
        problems.append("缺 viewBox，缩放会失真")
    import re

    m = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        if w < 200 or h < 200:
            problems.append(f"画布 {w}×{h} 过小（<200px），导出会糊")
    if "<text" not in svg and "<tspan" not in svg:
        problems.append("没有任何文字元素——像一张空图")
    black = len(re.findall(r'fill="#000(?:000)?"', svg)) + len(re.findall(r'fill="black"', svg))
    if black > 3:
        problems.append(f"纯黑填充 {black} 处（>3）：大面积纯黑在手机上很闷，换色板")
    density = len(re.findall(r"<(rect|text|circle|line|path|ellipse|polygon|image)\b", svg))
    if density < min_elements:
        problems.append(f"仅 {density} 个图形元素（<{min_elements}），版面太空")
    return problems


def emit(payload: dict) -> None:
    """技能脚本结果回传协议（executor 约定）：stdout 最后一行 ATELIER_RESULT。"""
    sys.stdout.write("ATELIER_RESULT " + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def skill_argv(argv: list[str] | None = None, desc: str = ""):
    """技能 run.py 统一参数：--params JSON / --out 目录 / --project。"""
    import argparse
    import os

    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("--params", default="{}")
    ap.add_argument("--out", default=os.environ.get("ATELIER_OUT", "."))
    ap.add_argument("--project", default=os.environ.get("ATELIER_PROJECT", "default"))
    ns = ap.parse_args(argv)
    try:
        params = json.loads(ns.params or "{}")
    except json.JSONDecodeError as e:
        print(f"--params 不是合法 JSON：{e}", file=sys.stderr)
        raise SystemExit(2)
    return params, Path(ns.out), ns.project


def load_params(params: dict, key: str, *, required: bool = False, default=None, label: str = ""):
    """取参数并做基础类型检查；required 缺失 → 退出码 2（明确 stderr）。"""
    v = params.get(key, default)
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            print(f"缺少必填参数 {key}" + (f"（{label}）" if label else ""), file=sys.stderr)
            raise SystemExit(2)
        return default
    return v
