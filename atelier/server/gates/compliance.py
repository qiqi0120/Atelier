"""门禁：极限词 / 医疗功效 / 违禁品词表（BLOCK，命中即阻断）。

**词表是短语级（≥2 字），不用单字。** 原因：BLOCK 级门禁误杀成本很高，
而中文单字歧义极大——「最」出现在「最后/最近/最好的朋友」里，「第一」出现在
「第一次做」里，全是正常表达。极限词要卡的是「全网第一」「行业第一」这种
**评价性极限用语**，所以按短语 + 正则上下文匹配（见 ``_PATTERNS``）。

命中后 message 里给出具体命中的词与分类，用户才知道改哪句。
"""

from __future__ import annotations

import re

from .base import GateInput, GateItem, Severity, ai_item
from .registry import register

__all__ = ["ComplianceGate", "scan_compliance"]


def _terms(*words: str) -> tuple[str, ...]:
    return words


#: 广告法意义上的评价性极限用语
#:
#: **只放高信号短语**：像「最好的」「最佳」这类裸最高级在日常口语里太常见
#: （「我最好的朋友」「最佳拍档」），BLOCK 级门禁误杀成本高，所以不放进来，
#: 改由 :data:`_PATTERNS` 的上下文正则来卡（只有「全网最」「行业最」这种才拦）。
_EXTREME = _terms(
    "全网第一", "全国第一", "行业第一", "世界第一", "排名第一", "销量第一",
    "第一品牌", "史上最", "史无前例", "前无古人", "绝无仅有", "独一无二", "无与伦比",
    "顶级", "极致", "巅峰", "100%有效", "百分之百有效", "永久有效",
    "彻底解决", "一次见效", "立刻见效", "无任何副作用",
)

#: 医疗功效宣称（非处方食品/普通内容不得宣称疗效）
_MEDICAL = _terms(
    "根治", "治愈", "药到病除", "特效", "特效药", "抗炎", "消炎", "抗癌",
    "防癌", "抗癌防癌", "祛斑", "祛痘", "瘦脸", "减肥", "丰胸", "增发",
    "防脱", "生发", "修复受损细胞", "激活细胞", "排毒养颜", "增强免疫力",
    "降血压", "降血糖", "治疗", "疗效", "药用", "无副作用", "纯天然无害",
    "医学证明有效", "临床验证有效",
)

#: 违禁品 / 灰产
_FORBIDDEN = _terms(
    "毒品", "冰毒", "海洛因", "大麻", "摇头丸", "制毒", "枪支", "枪械",
    "仿真枪", "子弹", "管制刀具", "匕首", "炸药", "走私", "代开发票",
    "发票代开", "办证", "刻章", "刷单", "代实名", "身份证代办", "外挂",
    "私服", "博彩", "赌博网站", "色情", "约炮", "一夜暴富", "割韭菜",
)

_ALL: dict[str, tuple[str, ...]] = {
    "极限用语": _EXTREME,
    "医疗功效": _MEDICAL,
    "违禁品": _FORBIDDEN,
}

#: 单字歧义词（最 / 第一）：用上下文正则卡，而不是直接当词。
#: 前面带「全网/行业/品牌」这类评价主体才算极限用语，「我最好的朋友」不算。
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("极限用语", re.compile(r"(?:全网|全国|行业|世界|史上|宇宙)最(?:好|强|低|高|优)")),
    ("极限用语", re.compile(r"(?:品牌|销量|口碑|质量|产品|性能)第一")),
    ("极限用语", re.compile(r"(?:品牌|产品|性能|效果|质量)(?:最)?(?:佳|优)(?:的)?(?:产品|方案|体验)?")),
    ("极限用语", re.compile(r"绝(?:对|不|无)可能")),
)

_FIX_HINTS: dict[str, str] = {
    "极限用语": "换成可验证的具体说法：「全网第一」→「我们跑了 300 篇同类内容对比」（有数据再说）",
    "医疗功效": "去掉疗效承诺：「根治痘印」→「我用了 3 个月，痘印变淡」（讲个人体验，不下结论）",
    "违禁品": "删掉相关词；确有需要就换成合规表述，并确认平台规则允许",
}


def scan_compliance(text: str, title: str | None = None) -> list[dict[str, str]]:
    """扫一遍，返回 ``[{category, term, where}]``（按出现顺序）。"""
    haystacks = [("正文", text or "")]
    if title:
        haystacks.append(("标题", title))
    hits: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for where, hay in haystacks:
        if not hay:
            continue
        for category, words in _ALL.items():
            for w in words:
                if w in hay and (category, w) not in seen:
                    seen.add((category, w))
                    hits.append({"category": category, "term": w, "where": where})
        for category, rx in _PATTERNS:
            for m in rx.finditer(hay):
                term = m.group(0)
                if (category, term) not in seen:
                    seen.add((category, term))
                    hits.append({"category": category, "term": term, "where": where})
    return hits


@register
class ComplianceGate:
    """极限词 / 医疗功效 / 违禁品词表；命中即阻断。"""

    id = "compliance"
    label = "合规词表"
    severity = Severity.BLOCK
    doc = "极限用语 / 医疗功效 / 违禁品三类词表，命中即阻断"

    def run(self, content: GateInput) -> GateItem:
        try:
            hits = scan_compliance(content.text, content.title)
        except Exception as exc:  # noqa: BLE001 - 词表本身坏了也要 fail-closed
            return ai_item(
                gate=self.id,
                label="合规词表（扫描异常）",
                passed=False,
                actual=f"{type(exc).__name__}: {exc}",
                limit=None,
                message=f"合规扫描失败，按命中处理：{exc}",
                fix_hint="跑 `atelier doctor` 看诊断；内容未落盘",
            )

        if not hits:
            return ai_item(
                gate=self.id,
                label="合规词表",
                passed=True,
                actual=0,
                limit=0,
                message="未命中极限词 / 医疗功效 / 违禁品词",
                fix_hint=None,
            )

        by_cat: dict[str, list[str]] = {}
        for h in hits:
            by_cat.setdefault(h["category"], []).append(f"{h['term']}（{h['where']}）")
        detail = "；".join(f"{cat}：" + "、".join(terms) for cat, terms in by_cat.items())
        first_cat = hits[0]["category"]
        return ai_item(
            gate=self.id,
            label=f"合规词表（{first_cat}）",
            passed=False,
            actual=detail,
            limit="0 个违规词",
            message=f"命中 {len(hits)} 个违规词 → {detail}",
            fix_hint=_FIX_HINTS.get(first_cat, "改掉上述词后重试"),
        )
