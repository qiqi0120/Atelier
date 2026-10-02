"""SPEC-08 §2 · F-E8 爆款拆解（P0）：粘贴对标内容 → 6 段式拆解。

6 段式按 **PRD F-E8** 冻结（概括/钩子/结构/为何火/可复制模板/结合画像出选题）。
与 `skills/viral-decode`（chat 入口）的 6 段名**有意不同**且本批不对齐——
两套口径的收敛记在 SPEC-08 §9 待办，动既有技能违反「不改既有文件加能力」。

「结合画像出选题」依赖画像注入：画像经 ``TurnRequest.profile`` 走 harness 的
system_prompt 通道，本模块只负责在段六的指令里**要求**模型结合画像；没传画像
时指令改为「说明当前是通用模式」——不装作有画像。
"""

from __future__ import annotations

import re
from typing import Any

from ..errors import ValidationError
from . import service

__all__ = ["DECODE_SECTIONS", "MIN_TEXT_CHARS", "run_decode"]

#: 6 段关键词（按 PRD F-E8 顺序冻结）；匹配 `##` 标题含关键词即认为该段存在
DECODE_SECTIONS: tuple[str, ...] = (
    "概括",
    "钩子",
    "结构",
    "为何火",
    "可复制模板",
    "结合画像出选题",
)

#: 原文最短长度（沿用 viral-decode「<40 字拆不动」的先例，SPEC-08 §2）
MIN_TEXT_CHARS = 40

_PROMPT = """你在为社交媒体创作者拆解一条爆款内容。只拆结构，不抄内容——抄结构可以，抄原文是偷。

## 对标原文

{text_block}

## 数据表现

{metrics_block}

## 你的任务

输出 Markdown，**恰好 6 个 `##` 段**，段名必须含这些关键词、顺序不许变：

1. `## 概括` — 客观概述这条内容是什么（主题、形式、篇幅），不加评价
2. `## 钩子` — 它哪一句/哪一段让人停下来，摘录原句；定位不到就如实写「未能定位」
3. `## 结构` — 用可复用的骨架描述（如「反常识结论 → 3 个证据 → 行动指令」）
4. `## 为何火` — 基于事实的归因，区分「结构性原因」与「猜测」，不编数据
5. `## 可复制模板` — 写成 `当 ⟨情况⟩ 时，⟨结论⟩ + ⟨证据⟩ + ⟨行动⟩` 的填空模板
6. `## 结合画像出选题` — {profile_line}给出 2–3 条可直接开工的选题（各一行，含角度）

不要输出这 6 段以外的前言、结语或解释。{goal_line}"""


def build_prompt(
    text: str, *, metrics: str = "", platform: str = "", goal: str = "", has_profile: bool
) -> str:
    """拼拆解 prompt。platform/goal 是上下文信息，缺省就明说，不留空段。"""
    text_block = text.strip()
    if platform:
        text_block = f"（平台：{platform}）\n{text_block}"
    metrics_block = metrics.strip() or "（未提供数据，不做效果归因）"
    profile_line = (
        "结合注入的创作者画像（定位/风格/受众），"
        if has_profile
        else "当前是通用模式、没有画像，先说明这一点，再"
    )
    goal_line = f"用户的目标是「{goal.strip()}」，选题要朝这个目标倾斜。" if goal.strip() else ""
    return _PROMPT.format(
        text_block=text_block,
        metrics_block=metrics_block,
        profile_line=profile_line,
        goal_line=goal_line,
    )


def parse_sections(markdown: str) -> dict[str, bool]:
    """按 ``##`` 标题关键词判段存在性。缺段由调用方报 ``DecodeIncomplete``。"""
    return {kw: bool(re.search(rf"^##.*{re.escape(kw)}", markdown, re.MULTILINE)) for kw in DECODE_SECTIONS}


def topic_seed(text: str) -> dict[str, str]:
    """一键存选题的种子：标题取原文首个非空行（截 80），角度留空给用户填。"""
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    title = first_line[: service.TITLE_MAX]
    return {"title": title, "angle": ""}


async def run_decode(
    *,
    text: str,
    metrics: str = "",
    platform: str = "",
    goal: str = "",
    profile_id: str | None = None,
) -> dict[str, Any]:
    """跑一次拆解。**不落库**——保存走 ``service.create_topic(source="decode")``。"""
    if not isinstance(text, str) or len(text.strip()) < MIN_TEXT_CHARS:
        raise ValidationError(
            f"对标原文太短（至少 {MIN_TEXT_CHARS} 字），拆不动",
            detail={"got": len(text.strip()) if isinstance(text, str) else 0},
            hint="贴完整文案或把截图里的文字整理进来；太短就先补上下文",
        )
    has_profile = bool(profile_id)
    raw = await service.run_ai_text(
        task="decode",
        prompt=build_prompt(text, metrics=metrics, platform=platform, goal=goal, has_profile=has_profile),
        profile_id=profile_id,
    )
    sections = parse_sections(raw)
    missing = [kw for kw, ok in sections.items() if not ok]
    if missing:
        raise service.DecodeIncomplete(
            f"拆解结果缺段：{'、'.join(missing)}",
            detail={"missing": missing, "expected": list(DECODE_SECTIONS)},
        )
    gate_report = service.gates_block_or_raise(raw, what="拆解结果")
    return {
        "decode_markdown": raw,
        "sections": sections,
        "gate_report": gate_report,
        "topic_seed": topic_seed(text),
    }
