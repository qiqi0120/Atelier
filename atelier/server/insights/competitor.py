"""SPEC-11 §2 · F-D10 竞品分析：粘贴竞品内容 → 选题 / 格式 / 爆款规律 三列表。

与拆解（F-E8）同款输入阈值（≥40 字）。**不落库**——出题的选题由前端经既有
``POST /topics``（source=manual、source_ref=竞品分析）逐条入库（SPEC-11 §0 D2）。
"""

from __future__ import annotations

from typing import Any

from atelier.server.errors import ValidationError
from atelier.server.topics import service as topic_service
from atelier.server.topics.decode import MIN_TEXT_CHARS

from . import service

__all__ = ["MAX_PER_LIST", "run_competitor"]

#: 每个列表的条数上限（SPEC-11 §2）
MAX_PER_LIST = 6

_PROMPT = """你在为社交媒体创作者分析一位竞品：从这条内容反推 TA 的选题策略、常用格式与爆款规律。

## 竞品原文

{text}

## 你的任务

输出**严格 JSON**，不要输出 JSON 以外的任何文字：

{{"topics": ["TA 在写的选题方向（具体到对象/切口，不是泛类目）"],
  "formats": ["TA 用的内容格式（如「三图一文」「口播+字幕」「对比测评」）"],
  "patterns": ["爆款规律（结构性归因，区分事实与猜测）"]}}

要求：每个数组 1 到 6 条，每条 2 到 80 字；只提炼结构规律，不抄原文句子。"""


async def run_competitor(*, text: str, profile_id: str | None = None) -> dict[str, Any]:
    """跑一次竞品分析。返回 ``{topics, formats, patterns, gate_report}``，不落库。"""
    if not isinstance(text, str) or len(text.strip()) < MIN_TEXT_CHARS:
        raise ValidationError(
            f"竞品原文太短（至少 {MIN_TEXT_CHARS} 字），分析不动",
            detail={"got": len(text.strip()) if isinstance(text, str) else 0},
            hint="贴竞品的完整文案；太短就多贴几条同类内容",
        )
    raw = await topic_service.run_ai_text(
        domain="insights", task="competitor",
        prompt=_PROMPT.format(text=text.strip()), profile_id=profile_id,
    )
    data = topic_service.extract_json(raw, task="competitor")
    if not isinstance(data, dict):
        raise topic_service.AIOutputInvalid(
            "竞品分析的输出不是 JSON 对象", detail={"task": "competitor", "head": raw[:200]}
        )
    try:
        topics = service.validate_str_list(data.get("topics"), label="topics")
        formats = service.validate_str_list(data.get("formats"), label="formats")
        patterns = service.validate_str_list(data.get("patterns"), label="patterns")
    except topic_service.AIOutputInvalid as exc:
        raise topic_service.AIOutputInvalid(
            exc.message, detail={"task": "competitor", **exc.detail}, hint=exc.hint
        ) from exc
    gate_report = topic_service.gates_block_or_raise(
        "\n".join("\n".join(x) for x in (topics, formats, patterns)), what="竞品分析"
    )
    return {"topics": topics, "formats": formats, "patterns": patterns, "gate_report": gate_report}
