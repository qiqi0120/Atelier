"""SPEC-12 §3 · F-E15 营销活动策划：节日/大促/新品 → 完整方案。

Markdown 冻结 5 段，缺段 ``InsightsIncomplete``。不落库（SPEC-12 §0 D6）。
"""

from __future__ import annotations

from typing import Any

from atelier.server.errors import ValidationError
from atelier.server.topics import service as topic_service

from . import service

__all__ = ["CAMPAIGN_SECTIONS", "run_campaign"]

CAMPAIGN_SECTIONS: tuple[str, ...] = ("活动目标", "主题创意", "节奏排期", "渠道分工", "预算与KPI")

_PROMPT = """你在为社交媒体创作者策划一场营销活动（主题：{theme}；场景：{occasion}）。{profile_line}

## 你的任务

输出 Markdown，**恰好 5 个 `##` 段**，段名必须含这些关键词、顺序不许变：

1. `## 活动目标` — 这次活动要达成什么（量化目标 + 为什么是它）
2. `## 主题创意` — 2~3 个活动主题/玩法概念，各配一句传播语
3. `## 节奏排期` — 预热/爆发/收尾三阶段的时间与动作，写到具体日期相对节点
4. `## 渠道分工` — 按平台（创作者自有渠道为主）分配内容形态与发布频次
5. `## 预算与KPI` — 预算框架（可标注「零成本」方案）+ 3~5 个可度量 KPI；没有数据回收渠道的指标如实标注

不要输出这 5 段以外的前言、结语或解释。"""


async def run_campaign(
    *, theme: str, occasion: str = "", profile_id: str | None = None
) -> dict[str, Any]:
    t = (theme or "").strip()
    if len(t) < 2:
        raise ValidationError(
            "活动主题至少 2 个字", detail={"theme": theme}, hint="写清楚要策划什么活动"
        )
    if len(t) > 60:
        raise ValidationError(f"活动主题最长 60 字（当前 {len(t)} 字）", detail={"max": 60})
    occasion_v = (occasion or "").strip()[:40] or "未指定（默认节日/大促/新品皆可套用）"
    profile_line = (
        "基于注入的创作者画像（定位/风格/受众/平台）策划。"
        if profile_id
        else "当前是通用模式、没有画像，先说明这一点，再给出通用框架。"
    )
    raw = await topic_service.run_ai_text(
        domain="insights", task="campaign",
        prompt=_PROMPT.format(theme=t, occasion=occasion_v, profile_line=profile_line),
        profile_id=profile_id,
    )
    sections = service.parse_markdown_sections(raw, CAMPAIGN_SECTIONS)
    missing = [kw for kw, ok in sections.items() if not ok]
    if missing:
        raise service.InsightsIncomplete(
            f"营销方案缺段：{'、'.join(missing)}",
            detail={"missing": missing, "expected": list(CAMPAIGN_SECTIONS)},
        )
    gate_report = topic_service.gates_block_or_raise(raw, what="营销活动策划")
    return {"markdown": raw, "sections": sections, "gate_report": gate_report}
