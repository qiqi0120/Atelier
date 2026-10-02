"""SPEC-11 §2 · F-E13 账号诊断：本地真实记录 → stats（代码持有）+ findings（AI 解读）。

**诚实模式是硬要求**（PLAN-M2 §2 ⚠️ 不做假数据）：

- ``publish_records`` < 5 条 → 返回 ``{insufficient: true, …}``，**不调模型**，
  不造分数——M1 在 cover_ratio 上踩过「看着能用的假数据」同类坑；
- stats（记录数 / 平台分布 / 近 30 天 / 选题流转）由 SQL 聚合，AI 只做解读——
  与评分结论同理（D4）；
- 限流信号 / 流量池阶段需要平台侧数据回收（M5），响应固定 ``notice`` 如实标注。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from atelier.server.core import db
from atelier.server.topics import service as topic_service

from . import service

__all__ = ["DIAGNOSE_DIMENSIONS", "MIN_RECORDS", "collect_stats", "run_diagnose"]

#: 触发诊断所需的最低发布记录数（SPEC-11 §0 D3）
MIN_RECORDS = 5
#: 诊断维度（冻结 4 维；限流/流量池依赖 M5，不在 AI 可报维度里）
DIAGNOSE_DIMENSIONS: tuple[str, ...] = ("垂直度", "定位清晰度", "更新节奏", "平台覆盖")
_STATUS_VALUES = ("good", "warn", "bad")
_ADVICE_MAX = 5
_NOTE_MAX = 120
_RECENT_TITLES = 10

_NOTICE = "限流信号与流量池阶段需要平台侧数据回收（M5），当前诊断仅基于本地记录。"

_PROMPT = """你在为社交媒体创作者做账号诊断。以下数据是**系统从本地记录统计的客观事实**，
你只做解读，不要自己编数字、不要质疑数据来源。

## 客观 stats（代码统计）

{stats_block}

## 最近发布的标题（最新在前，最多 {recent_n} 条）

{titles_block}

## 你的任务

基于以上事实，输出**严格 JSON**，不要输出 JSON 以外的任何文字：

{{"findings": [{{"dimension": "维度名", "status": "good|warn|bad", "note": "≤120字，引用具体数据支撑"}}],
  "advice": ["下一步动作（可执行，1 到 5 条）"]}}

维度**恰好 4 个**、顺序不许变：垂直度、定位清晰度、更新节奏、平台覆盖。
note 必须引用 stats 里的具体数字；数据撑不出结论就如实写「数据不足以下判断」并给 status=warn。"""


def collect_stats(today: datetime | None = None) -> dict[str, Any]:
    """本地记录的客观统计（D4：代码持有，AI 只引用）。"""
    today = today or datetime.now(UTC)
    cutoff = (today - timedelta(days=30)).isoformat(timespec="seconds")
    with db.db_session(commit=False) as conn:
        total = conn.execute("SELECT COUNT(*) FROM publish_records").fetchone()[0]
        by_platform = {
            r["platform"]: r["n"]
            for r in conn.execute(
                "SELECT platform, COUNT(*) AS n FROM publish_records GROUP BY platform ORDER BY n DESC"
            ).fetchall()
        }
        failed = conn.execute(
            "SELECT COUNT(*) FROM publish_records WHERE status = 'failed'"
        ).fetchone()[0]
        last30 = conn.execute(
            "SELECT COUNT(*) FROM publish_records WHERE created_at >= ?", (cutoff,)
        ).fetchone()[0]
        drafts = conn.execute("SELECT COUNT(*) FROM publish_drafts").fetchone()[0]
        topic_rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM topics GROUP BY status"
        ).fetchall()
        recent = [
            r["title"] or "（无标题）"
            for r in conn.execute(
                "SELECT title FROM publish_records ORDER BY created_at DESC LIMIT ?",
                (_RECENT_TITLES,),
            ).fetchall()
        ]
    topics_flow = {s: 0 for s in ("todo", "doing", "done")}
    for r in topic_rows:
        if r["status"] in topics_flow:
            topics_flow[r["status"]] = r["n"]
    return {
        "records_total": total,
        "records_last_30d": last30,
        "records_failed": failed,
        "by_platform": by_platform,
        "drafts_total": drafts,
        "topics_flow": topics_flow,
        "recent_titles": recent,
    }


async def run_diagnose(*, profile_id: str | None = None) -> dict[str, Any]:
    """跑一次诊断。记录不足时诚实返回，不调模型（D3）。"""
    stats = collect_stats()
    if stats["records_total"] < MIN_RECORDS:
        return {
            "insufficient": True,
            "stats": stats,
            "need": MIN_RECORDS,
            "message": f"发布满 {MIN_RECORDS} 条后才有诊断（当前 {stats['records_total']} 条）——不编造分数",
        }

    titles_block = "\n".join(f"- {t}" for t in stats["recent_titles"]) or "（无标题记录）"
    raw = await topic_service.run_ai_text(
        domain="insights", task="diagnose",
        prompt=_PROMPT.format(
            stats_block=json.dumps(stats, ensure_ascii=False, indent=2),
            recent_n=len(stats["recent_titles"]),
            titles_block=titles_block,
        ),
        profile_id=profile_id,
    )
    data = topic_service.extract_json(raw, task="diagnose")
    if not isinstance(data, dict):
        raise topic_service.AIOutputInvalid(
            "诊断的输出不是 JSON 对象", detail={"task": "diagnose", "head": raw[:200]}
        )

    findings_raw = data.get("findings")
    if not isinstance(findings_raw, list):
        raise topic_service.AIOutputInvalid(
            "诊断输出缺 findings 数组", detail={"task": "diagnose", "head": raw[:200]}
        )
    findings: list[dict[str, str]] = []
    for it in findings_raw:
        if not isinstance(it, dict):
            raise topic_service.AIOutputInvalid(
                "findings 里有非对象元素", detail={"task": "diagnose", "item": str(it)[:120]}
            )
        dim = it.get("dimension")
        if dim not in DIAGNOSE_DIMENSIONS:
            raise topic_service.AIOutputInvalid(
                f"诊断维度「{dim}」不在冻结的 4 维里",
                detail={"task": "diagnose", "dimension": str(dim)[:60]},
            )
        status = it.get("status")
        if status not in _STATUS_VALUES:
            raise topic_service.AIOutputInvalid(
                f"维度「{dim}」的 status 非法（只允许 good/warn/bad）",
                detail={"task": "diagnose", "status": str(status)[:60]},
            )
        note = it.get("note")
        if not isinstance(note, str) or not note.strip():
            raise topic_service.AIOutputInvalid(
                f"维度「{dim}」缺 note", detail={"task": "diagnose"}
            )
        note = note.strip()
        if len(note) > _NOTE_MAX:
            raise topic_service.AIOutputInvalid(
                f"维度「{dim}」的 note 超过 {_NOTE_MAX} 字", detail={"task": "diagnose"}
            )
        findings.append({"dimension": dim, "status": status, "note": note})
    if len(findings) != len(DIAGNOSE_DIMENSIONS):
        raise topic_service.AIOutputInvalid(
            f"findings 应为 {len(DIAGNOSE_DIMENSIONS)} 条（当前 {len(findings)} 条）",
            detail={"task": "diagnose", "count": len(findings)},
        )
    advice = service.validate_str_list(data.get("advice"), label="advice",
                                       max_items=_ADVICE_MAX, max_len=_NOTE_MAX)

    gate_report = topic_service.gates_block_or_raise(
        "\n".join(f"{f['dimension']}：{f['note']}" for f in findings)
        + "\n"
        + "\n".join(advice),
        what="账号诊断",
    )
    return {
        "insufficient": False,
        "stats": stats,
        "findings": findings,
        "advice": advice,
        "notice": _NOTICE,
        "gate_report": gate_report,
    }
