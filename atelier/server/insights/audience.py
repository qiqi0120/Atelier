"""SPEC-11 §2 · F-E14 受众画像卡：画像 → 人群一句 + 痛点/场景/偏好/避坑。

严格 JSON 卡片契约；无画像时出通用版并如实标注（prompt 要求说明通用模式）。
不落库（D2）。
"""

from __future__ import annotations

from typing import Any

from atelier.server.topics import service as topic_service

from . import service

__all__ = ["CARD_FIELDS", "PERSONA_MAX", "run_audience"]

#: 卡片字段（persona 一句话 + 四个数组），冻结（SPEC-11 §2）
CARD_FIELDS: tuple[str, ...] = ("pains", "scenarios", "preferences", "notes")
PERSONA_MAX = 60

_PROMPT = """你在为社交媒体创作者提炼受众画像卡。{profile_line}

## 你的任务

输出**严格 JSON**，不要输出 JSON 以外的任何文字：

{{"persona": "一句话说清目标人群是谁（不超过60字）",
  "pains": ["TA 的具体痛点（场景化的，不是标签）"],
  "scenarios": ["TA 会刷到/使用内容的典型场景"],
  "preferences": ["TA 偏好的内容形式与表达方式"],
  "notes": ["做内容时的避坑提醒（雷区/忌讳/疲劳点）"]}}

要求：persona 不超过 60 字；四个数组各 1 到 6 条、每条 2 到 80 字；基于合理推断，
不编造调研数据。{general_line}"""


async def run_audience(*, profile_id: str | None = None) -> dict[str, Any]:
    """跑一次受众画像。返回 ``{card, gate_report}``，不落库。"""
    profile_line = "基于注入的创作者画像（定位/风格/受众/平台）推断 TA 的受众。" if profile_id else ""
    general_line = (
        "" if profile_id else "没有画像时给出通用版，并在 persona 开头标注「通用版：」如实说明。"
    )
    raw = await topic_service.run_ai_text(
        domain="insights", task="audience",
        prompt=_PROMPT.format(profile_line=profile_line, general_line=general_line),
        profile_id=profile_id,
    )
    data = topic_service.extract_json(raw, task="audience")
    if not isinstance(data, dict):
        raise topic_service.AIOutputInvalid(
            "受众画像的输出不是 JSON 对象", detail={"task": "audience", "head": raw[:200]}
        )
    persona = data.get("persona")
    if not isinstance(persona, str) or not persona.strip():
        raise topic_service.AIOutputInvalid(
            "受众画像缺 persona", detail={"task": "audience"}
        )
    persona = persona.strip()
    if len(persona) > PERSONA_MAX:
        raise topic_service.AIOutputInvalid(
            f"persona 超过 {PERSONA_MAX} 字（当前 {len(persona)} 字）",
            detail={"task": "audience", "persona": persona[:120]},
        )
    card: dict[str, Any] = {"persona": persona}
    for field in CARD_FIELDS:
        card[field] = service.validate_str_list(data.get(field), label=field)
    gate_report = topic_service.gates_block_or_raise(
        "\n".join([persona, *("\n".join(card[f]) for f in CARD_FIELDS)]), what="受众画像"
    )
    return {"card": card, "gate_report": gate_report}
