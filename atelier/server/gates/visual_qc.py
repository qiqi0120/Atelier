"""门禁：视觉产出结构质检（**WARN**，SPEC-13 §0 D3）。

M3 视觉技能产出 SVG 时，这里对**文本形态的 SVG**（``GateInput.text`` 含
``<svg``）做确定性结构检查：viewBox、画布尺寸、文字元素、纯黑面积、元素密度。
不合格只告警提示重做（与 ai_flavor 同级，不阻断落盘）——真正的位图/排版级
QC 在各视觉 run.py 内置（它持有布局数据），本门禁兜住 agent 产出的 SVG。

非 SVG 文本直接通过（passed=True），不产出噪音。
"""

from __future__ import annotations

from .base import GateInput, GateItem, Severity, ai_item
from .registry import register

__all__ = ["VisualQcGate"]

#: 密度下限：低于它说明版面过空（一张像样的信息图至少这几个图元）
MIN_ELEMENTS = 4


def _problems(svg: str) -> list[str]:
    import re

    problems: list[str] = []
    if "viewBox" not in svg:
        problems.append("缺 viewBox")
    m = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
    if m and (int(m.group(1)) < 200 or int(m.group(2)) < 200):
        problems.append(f"画布 {m.group(1)}×{m.group(2)} 过小（<200px）")
    if "<text" not in svg and "<tspan" not in svg:
        problems.append("没有任何文字元素")
    black = len(re.findall(r'fill="#000000"|fill="black"', svg))
    if black > 3:
        problems.append(f"纯黑填充 {black} 处")
    density = len(re.findall(r"<(rect|text|circle|line|path|ellipse|polygon|image)\b", svg))
    if density < MIN_ELEMENTS:
        problems.append(f"仅 {density} 个图形元素，版面过空")
    return problems


@register
class VisualQcGate:
    id = "visual_qc"
    label = "视觉质检（SVG 结构）"
    severity = Severity.WARN
    doc = "对 SVG 产出做确定性结构检查（viewBox/尺寸/文字/纯黑/密度），不合格提示重做，不阻断落盘。"

    def run(self, content: GateInput) -> GateItem:
        text = (content.text or "").strip()
        if "<svg" not in text:
            return ai_item(
                gate=self.id, label=self.label, severity=self.severity,
                passed=True, actual="非 SVG 内容", limit=None,
                message="不是 SVG 产出，视觉质检跳过", fix_hint=None,
            )
        problems = _problems(text)
        if not problems:
            return ai_item(
                gate=self.id, label=self.label, severity=self.severity,
                passed=True, actual="结构检查通过", limit=None,
                message="SVG 结构质检通过（viewBox/尺寸/文字/密度）", fix_hint=None,
            )
        return ai_item(
            gate=self.id, label=self.label, severity=self.severity,
            passed=False, actual="；".join(problems), limit="viewBox + ≥200px + 有文字 + 密度≥4",
            message=f"SVG 结构质检发现 {len(problems)} 个问题：{'；'.join(problems)}",
            fix_hint="修正画布尺寸与文字排版后重做；参考技能里的 theme 参数换色板",
        )
