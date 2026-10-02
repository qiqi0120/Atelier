"""SPEC-11 §2 · F-E12 内容策略：画像 → 内容支柱架构 / 受众路径 / 90 天节奏 / KPI。

Markdown 冻结 4 段（段名含关键词），缺段 ``InsightsIncomplete``。不落库（D2）。
"""

from __future__ import annotations

from typing import Any

from atelier.server.topics import service as topic_service

from . import service

__all__ = ["STRATEGY_SECTIONS", "run_strategy"]

#: 4 段关键词（按 PRD F-E12 冻结顺序）；`##` 标题含关键词即认为该段存在
STRATEGY_SECTIONS: tuple[str, ...] = ("内容支柱", "受众路径", "90 天", "KPI")

_PROMPT = """你在为社交媒体创作者制定内容策略。{profile_line}

## 你的任务

输出 Markdown，**恰好 4 个 `##` 段**，段名必须含这些关键词、顺序不许变：

1. `## 内容支柱架构` — 3~4 个内容支柱（方向 + 占比 + 承担的角色），支柱要能覆盖主要受众需求
2. `## 受众路径` — 从「刷到」到「关注」到「转化」的路径设计，每段一条钩子策略
3. `## 90 天节奏` — 按月分三阶段（月度目标 + 每周几条 + 主打支柱），写具体到可执行
4. `## KPI` — 3~5 个可度量的指标与 90 天目标值；标注哪些指标当前**没有数据回收渠道**、先看什么替代信号

不要输出这 4 段以外的前言、结语或解释。"""


async def run_strategy(*, profile_id: str | None = None) -> dict[str, Any]:
    """跑一次策略生成。返回 ``{markdown, sections, gate_report}``，不落库。"""
    profile_line = (
        "基于注入的创作者画像（定位/风格/受众/平台）制定。"
        if profile_id
        else "当前是通用模式、没有画像，先说明这一点，再给出通用策略框架。"
    )
    raw = await topic_service.run_ai_text(
        domain="insights", task="strategy",
        prompt=_PROMPT.format(profile_line=profile_line), profile_id=profile_id,
    )
    sections = service.parse_markdown_sections(raw, STRATEGY_SECTIONS)
    missing = [kw for kw, ok in sections.items() if not ok]
    if missing:
        raise service.InsightsIncomplete(
            f"策略结果缺段：{'、'.join(missing)}",
            detail={"missing": missing, "expected": list(STRATEGY_SECTIONS)},
        )
    gate_report = topic_service.gates_block_or_raise(raw, what="内容策略")
    return {"markdown": raw, "sections": sections, "gate_report": gate_report}
