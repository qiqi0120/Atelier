"""SPEC-12 §3 · F-E17 品牌合作方案：商单/联名策划。

Markdown 冻结 5 段，缺段 ``InsightsIncomplete``。不落库（SPEC-12 §0 D6）。
"""

from __future__ import annotations

from typing import Any

from atelier.server.errors import ValidationError
from atelier.server.topics import service as topic_service

from . import service

__all__ = ["BRIEF_MIN", "SPONSORSHIP_SECTIONS", "run_sponsorship"]

SPONSORSHIP_SECTIONS: tuple[str, ...] = ("合作解读", "创意方案", "内容形式", "报价建议", "风险与边界")

#: 商单 brief 是贴进来的品牌需求，至少要说清楚合作什么
BRIEF_MIN = 10
BRIEF_MAX = 20000

_PROMPT = """你在帮社交媒体创作者写一份品牌合作提案（商单/联名）。品牌方需求如下：

{brief}
{brand_line}
{profile_line}

## 你的任务

输出 Markdown，**恰好 5 个 `##` 段**，段名必须含这些关键词、顺序不许变：

1. `## 合作解读` — 品牌方要什么、创作者能给什么、匹配点在哪
2. `## 创意方案` — 2~3 个合作创意概念，各配一句核心传播点
3. `## 内容形式` — 每个创意对应的交付物清单（条数/形态/平台/时长或字数）
4. `## 报价建议` — 报价结构（保底+浮动）与谈判要点；没有行情数据时给出**估算逻辑**并如实标注是估算
5. `## 风险与边界` — 内容底线、独家/竞业条款、档期与修改次数等要谈清楚的边界，至少 3 条

不要输出这 5 段以外的前言、结语或解释。"""


async def run_sponsorship(
    *, brief: str, brand: str = "", profile_id: str | None = None
) -> dict[str, Any]:
    b = (brief or "").strip()
    if len(b) < BRIEF_MIN:
        raise ValidationError(
            f"品牌需求至少 {BRIEF_MIN} 个字",
            detail={"brief": brief, "min": BRIEF_MIN},
            hint="把品牌方的需求原文贴进来（合作什么、投什么平台、预期效果）",
        )
    if len(b) > BRIEF_MAX:
        raise ValidationError(
            f"品牌需求最长 {BRIEF_MAX} 字（当前 {len(b)} 字）", detail={"max": BRIEF_MAX}
        )
    brand_line = f"品牌方：{brand.strip()[:60]}" if (brand or "").strip() else "品牌方：需求里未注明"
    profile_line = (
        "提案口径基于注入的创作者画像（定位/风格/受众/平台）。"
        if profile_id
        else "当前是通用模式、没有画像，先说明这一点，再给出通用提案框架。"
    )
    raw = await topic_service.run_ai_text(
        domain="insights", task="sponsorship",
        prompt=_PROMPT.format(brief=b, brand_line=brand_line, profile_line=profile_line),
        profile_id=profile_id,
    )
    sections = service.parse_markdown_sections(raw, SPONSORSHIP_SECTIONS)
    missing = [kw for kw, ok in sections.items() if not ok]
    if missing:
        raise service.InsightsIncomplete(
            f"商单方案缺段：{'、'.join(missing)}",
            detail={"missing": missing, "expected": list(SPONSORSHIP_SECTIONS)},
        )
    gate_report = topic_service.gates_block_or_raise(raw, what="品牌合作方案")
    return {"markdown": raw, "sections": sections, "gate_report": gate_report}
