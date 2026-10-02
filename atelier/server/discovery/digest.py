"""SPEC-12 §2 · F-D8 热点日报：素材池 → AI 结构化日报（落 ``hot_digests``）。

诚实边界（SPEC-12 §0 D3）：素材池没有 pending 条目时返回
``{insufficient: true, ...}`` **不调模型**；素材清单由代码聚合注入 prompt，
AI 只做归类与解读、不许编造素材里没有的信息；缺段 → ``DiscoveryIncomplete``。
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from atelier.server.core import db
from atelier.server.topics import service as topic_service

from . import service

__all__ = ["DIGEST_MAX_ENTRIES", "DIGEST_SECTIONS", "run_digest"]

#: 冻结 3 段（SPEC-12 §2）；`##` 标题含关键词即认为该段存在
DIGEST_SECTIONS: tuple[str, ...] = ("热点盘点", "机会点", "建议动作")
#: 单次日报最多带进的素材条数（防 prompt 失控）
DIGEST_MAX_ENTRIES = 40

_PROMPT = """你在为社交媒体创作者整理今日热点日报。素材全部来自下方清单——**只解读清单里有的信息，不许编造清单外的热点或数据**。

## 素材清单（编号 | 日期 | 来源平台 | 热度 | 标题）

{entries}

## 你的任务

输出 Markdown，**恰好 3 个 `##` 段**，段名必须含这些关键词、顺序不许变：

1. `## 热点盘点` — 逐条或分组归类清单素材，每条一句话点评（引用素材编号）
2. `## 机会点` — 哪些热点与创作者方向相关、能蹭、怎么蹭（2~4 条，注明对应素材编号）
3. `## 建议动作` — 今天就能执行的动作（1~3 条，每条注明对应素材编号与预期产出）

不要输出这 3 段以外的前言、结语或解释；清单为空的信息不要脑补。"""


def _collect_pending() -> list[dict[str, Any]]:
    with db.db_session(commit=False) as conn:
        rows = conn.execute(
            "SELECT * FROM hot_entries WHERE status = 'pending'"
            " ORDER BY created_at DESC LIMIT ?",
            (DIGEST_MAX_ENTRIES,),
        ).fetchall()
    return [service.row_to_hot_entry(r) for r in rows]


async def run_digest(*, profile_id: str | None = None) -> dict[str, Any]:
    """生成一次日报。返回 insufficient 或 ``{digest, markdown, sections, gate_report}``。"""
    entries = _collect_pending()
    if not entries:
        return {
            "insufficient": True,
            "need": 1,
            "stats": service.list_hot()["counts"],
            "message": "素材池没有待处理的热点（pending=0）——先手工导入或从订阅转入，再生成日报，不编造热点",
        }
    lines = []
    for i, e in enumerate(entries, 1):
        heat = f" | 热度 {e['heat']}" if e["heat"] else ""
        lines.append(f"{i}. [{e['entry_date'] or '日期未知'}] {e['platform'] or '未知平台'}{heat} | {e['title']}")
    raw = await topic_service.run_ai_text(
        domain="discovery",
        task="digest",
        prompt=_PROMPT.format(entries="\n".join(lines)),
        profile_id=profile_id,
    )
    sections = {
        kw: bool(re.search(rf"^##.*{re.escape(kw)}", raw, re.MULTILINE))
        for kw in DIGEST_SECTIONS
    }
    missing = [kw for kw, ok in sections.items() if not ok]
    if missing:
        raise service.DiscoveryIncomplete(
            f"日报缺段：{'、'.join(missing)}",
            detail={"missing": missing, "expected": list(DIGEST_SECTIONS)},
        )
    gate_report = topic_service.gates_block_or_raise(raw, what="热点日报")
    did = f"digest-{uuid.uuid4().hex[:16]}"
    dates = sorted(e["entry_date"] for e in entries if e["entry_date"])
    now = db.utcnow()
    title = f"热点日报 · {datetime.now(UTC).date().isoformat()}"
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO hot_digests (id, title, window_start, window_end, markdown,"
            " entry_ids, created_at) VALUES (?,?,?,?,?,?,?)",
            (did, title, dates[0] if dates else "", dates[-1] if dates else "",
             raw, db.dumps([e["id"] for e in entries]), now),
        )
        for e in entries:
            conn.execute(
                "UPDATE hot_entries SET status = 'digested', digest_id = ?, updated_at = ? WHERE id = ?",
                (did, now, e["id"]),
            )
    digest = service.get_digest(did)
    return {
        "insufficient": False,
        "digest": digest,
        "markdown": raw,
        "sections": sections,
        "entry_count": len(entries),
        "gate_report": gate_report,
    }
