"""SPEC-11 · 分析域服务层：域内错误 + 共用校验助手。

AI 调用 / JSON 提取 / 门禁**不复用本模块**——直接用
:mod:`atelier.server.topics.service` 的原语（``run_ai_text`` 传
``domain="insights"``、``extract_json``、``gates_block_or_raise``，
SPEC-11 §0 D1）。这里只放分析域自己的契约件。
"""

from __future__ import annotations

import re
from typing import Any

from atelier.server.errors import AtelierError
from atelier.server.topics.service import AIOutputInvalid

__all__ = [
    "ITEM_MAX",
    "LIST_MAX",
    "PERSONA_MAX",
    "InsightsIncomplete",
    "parse_markdown_sections",
    "validate_str_list",
]

#: 通用条目上限（SPEC-11 §0 D6）：数组 1..6 条、单项 2..80 字
LIST_MAX = 6
ITEM_MAX = 80
PERSONA_MAX = 60


class InsightsIncomplete(AtelierError):
    """分析结果缺段（SPEC-11 §0 D5）。缺段如实报错，不硬编补齐。"""

    code = "InsightsIncomplete"
    http = 422
    default_message = "分析结果不完整：缺少规定的段落"
    default_hint = "重试一次；连续失败就把任务拆小或换模型"


def parse_markdown_sections(markdown: str, keywords: tuple[str, ...]) -> dict[str, bool]:
    """按 ``##`` 标题关键词判段存在性（与 topics/decode.parse_sections 同口径）。"""
    return {
        kw: bool(re.search(rf"^##.*{re.escape(kw)}", markdown, re.MULTILINE))
        for kw in keywords
    }


def validate_str_list(value: Any, *, label: str, max_items: int = LIST_MAX,
                      max_len: int = ITEM_MAX, min_len: int = 2) -> list[str]:
    """字符串数组契约：非空、1..max_items 条、每条 strip 后 min_len..max_len 字。

    这是**模型输出**校验：违约按 ``AIOutputInvalid`` 报（topics 域的错误类，
    SPEC-11 §0 D5 不新增错误码），不截断、不编造（D6）。
    """
    if not isinstance(value, list) or not value:
        raise AIOutputInvalid(f"{label} 缺失或不是非空数组", detail={"field": label, "got": str(value)[:120]})
    if len(value) > max_items:
        raise AIOutputInvalid(
            f"{label} 返回 {len(value)} 条，超过上限 {max_items}",
            detail={"field": label, "count": len(value)},
        )
    out: list[str] = []
    for v in value:
        if not isinstance(v, str) or len(v.strip()) < min_len:
            raise AIOutputInvalid(f"{label} 里有空项或过短项", detail={"field": label, "item": str(v)[:120]})
        s = v.strip()
        if len(s) > max_len:
            raise AIOutputInvalid(
                f"{label} 单项超过 {max_len} 字（当前 {len(s)} 字）",
                detail={"field": label, "item": s[:120]},
            )
        out.append(s)
    return out
