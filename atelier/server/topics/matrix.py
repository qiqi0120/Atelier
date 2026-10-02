"""SPEC-08 §2 · F-E10 内容矩阵：内容支柱 × 格式 交叉生成选题池。

生成结果**整批入库**（status=todo、source=matrix、source_ref=pillar×format）——
出口标准是「一键生成选题池」，落了库才算池。规模护栏：组合数
``pillars × formats × per_combo > 60`` 在参数层拒绝，**不调模型**（省钱省时间，
错误体告诉用户怎么缩小范围）。
"""

from __future__ import annotations

import uuid
from typing import Any

from ..core import db
from . import service
from .service import AIOutputInvalid, ValidationError

__all__ = ["MAX_COMBOS", "MAX_PILLARS", "PER_COMBO_RANGE", "run_matrix"]

MAX_PILLARS = 6
MAX_FORMATS = 6
#: 每格条数允许范围（SPEC-08 §2）
PER_COMBO_RANGE = (1, 3)
#: 组合总量上限，超出直接 422（SPEC-08 §2）
MAX_COMBOS = 60
#: 模型单次最多允许返回的条数（防跑飞；超过视为违约）
MAX_ITEMS = 100

_PILLAR_LIMIT = 20  # 单个支柱/格式短语长度


def _validate_list(raw: Any, label: str) -> list[str]:
    if not isinstance(raw, list) or not raw:
        raise ValidationError(f"{label} 必须是非空字符串数组", detail={label: raw})
    items: list[str] = []
    for v in raw:
        if not isinstance(v, str) or not v.strip():
            raise ValidationError(f"{label} 里有空项", detail={label: raw})
        s = v.strip()
        if len(s) > _PILLAR_LIMIT:
            raise ValidationError(
                f"{label} 单项最长 {_PILLAR_LIMIT} 字（当前 {len(s)} 字）",
                detail={"item": s},
                hint="支柱/格式用短语，展开写进选题角度",
            )
        items.append(s)
    return items


def build_prompt(pillars: list[str], formats: list[str], per_combo: int) -> str:
    pillar_lines = "\n".join(f"- {p}" for p in pillars)
    format_lines = "、".join(formats)
    return f"""你在为社交媒体创作者搭建内容矩阵：内容支柱 × 内容格式 交叉出选题。

## 内容支柱（账号的选题方向）

{pillar_lines}

## 内容格式

{format_lines}

## 你的任务

每个「支柱 × 格式」组合生成 {per_combo} 条选题，共 {len(pillars) * len(formats) * per_combo} 条。
标题要具体到能直接开工（有对象/有数字/有切口），不要「聊聊XX」「浅谈XX」这类空标题；
每条配一句角度说明。

输出**严格 JSON**，不要输出 JSON 以外的任何文字：

{{"items": [{{"pillar": "支柱原词", "format": "格式原词", "title": "不超过80字", "angle": "一句话角度"}}]}}"""


async def run_matrix(
    *,
    pillars: list[str],
    formats: list[str],
    per_combo: int = 2,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """生成矩阵选题并整批入库。返回 ``{items, count, gate_report}``。"""
    ps = _validate_list(pillars, "pillars")
    fs = _validate_list(formats, "formats")
    if len(ps) > MAX_PILLARS or len(fs) > MAX_FORMATS:
        raise ValidationError(
            f"支柱最多 {MAX_PILLARS} 个、格式最多 {MAX_FORMATS} 个",
            detail={"pillars": len(ps), "formats": len(fs)},
        )
    if isinstance(per_combo, bool) or not isinstance(per_combo, int) \
            or not PER_COMBO_RANGE[0] <= per_combo <= PER_COMBO_RANGE[1]:
        raise ValidationError(
            f"per_combo 必须是 {PER_COMBO_RANGE[0]}..{PER_COMBO_RANGE[1]} 的整数",
            detail={"per_combo": per_combo},
        )
    combos = len(ps) * len(fs) * per_combo
    if combos > MAX_COMBOS:
        raise ValidationError(
            f"组合数 {combos} 超过单次上限 {MAX_COMBOS}",
            detail={"combos": combos, "max": MAX_COMBOS},
            hint="缩小支柱/格式数量或把 per_combo 降到 1，分多次生成",
        )

    raw = await service.run_ai_text(
        task="matrix", prompt=build_prompt(ps, fs, per_combo), profile_id=profile_id
    )
    data = service.extract_json(raw, task="matrix")
    items_raw = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items_raw, list) or not items_raw:
        raise AIOutputInvalid("矩阵输出缺少 items 数组", detail={"task": "matrix", "head": raw[:200]})
    if len(items_raw) > MAX_ITEMS:
        raise AIOutputInvalid(
            f"矩阵返回 {len(items_raw)} 条，超过单次上限 {MAX_ITEMS}",
            detail={"task": "matrix", "count": len(items_raw)},
        )

    parsed: list[dict[str, str]] = []
    for it in items_raw:
        if not isinstance(it, dict):
            raise AIOutputInvalid("items 里有非对象元素", detail={"task": "matrix", "item": str(it)[:120]})
        title = service.validate_title(it.get("title"))  # 空/超长 → ValidationError(422)
        angle = str(it.get("angle") or "").strip()[: service.ANGLE_MAX]
        pillar = str(it.get("pillar") or "").strip()
        fmt = str(it.get("format") or "").strip()
        parsed.append({"title": title, "angle": angle, "source_ref": f"{pillar}×{fmt}".strip("×")})

    joined = "\n".join(p["title"] for p in parsed)
    gate_report = service.gates_block_or_raise(joined, what="矩阵选题")

    created = db.utcnow()
    ids: list[str] = []
    with db.db_session() as conn:
        for p in parsed:
            tid = f"topic-{uuid.uuid4().hex[:16]}"
            ids.append(tid)
            conn.execute(
                "INSERT INTO topics (id, profile_id, title, angle, source, source_ref, status,"
                " decode, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (tid, profile_id, p["title"], p["angle"], "matrix", p["source_ref"],
                 "todo", None, created, created),
            )
    with db.db_session(commit=False) as conn:
        rows = conn.execute(
            f"SELECT * FROM topics WHERE id IN ({', '.join('?' * len(ids))}) ORDER BY rowid",
            ids,
        ).fetchall()
    items = [service.row_to_topic(r) for r in rows]
    return {"items": items, "count": len(items), "gate_report": gate_report}
