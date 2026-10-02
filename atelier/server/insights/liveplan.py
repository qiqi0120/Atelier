"""SPEC-12 §3 · F-E16 直播策划：直播流程 / 话术 / 互动设计。

Markdown 冻结 5 段，缺段 ``InsightsIncomplete``。不落库（SPEC-12 §0 D6）。
"""

from __future__ import annotations

from typing import Any

from atelier.server.errors import ValidationError
from atelier.server.topics import service as topic_service

from . import service

__all__ = ["LIVEPLAN_SECTIONS", "run_liveplan"]

LIVEPLAN_SECTIONS: tuple[str, ...] = ("直播目标", "流程脚本", "话术要点", "互动设计", "风险预案")

_PROMPT = """你在为社交媒体创作者策划一场直播（主题：{topic}；时长：{duration}）。{profile_line}

## 你的任务

输出 Markdown，**恰好 5 个 `##` 段**，段名必须含这些关键词、顺序不许变：

1. `## 直播目标` — 这场直播达成什么（拉新/转化/固粉，量化）
2. `## 流程脚本` — 按 {duration} 的时间轴写环节表（时间点 + 环节 + 要做什么），覆盖开场/主体/收尾
3. `## 话术要点` — 开场留人、讲解放大、转化逼单的关键话术各 1~2 句（口语，不要播音腔）
4. `## 互动设计` — 3~5 个互动机制（评论引导/抽奖/连麦等）与投放时点
5. `## 风险预案` — 冷场/设备故障/违规敏感/恶意刷屏的应对，至少 3 条

不要输出这 5 段以外的前言、结语或解释。"""


async def run_liveplan(
    *, topic: str, duration: str = "", profile_id: str | None = None
) -> dict[str, Any]:
    t = (topic or "").strip()
    if len(t) < 2:
        raise ValidationError(
            "直播主题至少 2 个字", detail={"topic": topic}, hint="写清楚这场直播讲什么"
        )
    if len(t) > 60:
        raise ValidationError(f"直播主题最长 60 字（当前 {len(t)} 字）", detail={"max": 60})
    duration_v = (duration or "").strip()[:20] or "90 分钟"
    profile_line = (
        "基于注入的创作者画像（定位/风格/受众/平台）策划。"
        if profile_id
        else "当前是通用模式、没有画像，先说明这一点，再给出通用框架。"
    )
    raw = await topic_service.run_ai_text(
        domain="insights", task="liveplan",
        prompt=_PROMPT.format(topic=t, duration=duration_v, profile_line=profile_line),
        profile_id=profile_id,
    )
    sections = service.parse_markdown_sections(raw, LIVEPLAN_SECTIONS)
    missing = [kw for kw, ok in sections.items() if not ok]
    if missing:
        raise service.InsightsIncomplete(
            f"直播方案缺段：{'、'.join(missing)}",
            detail={"missing": missing, "expected": list(LIVEPLAN_SECTIONS)},
        )
    gate_report = topic_service.gates_block_or_raise(raw, what="直播策划")
    return {"markdown": raw, "sections": sections, "gate_report": gate_report}
