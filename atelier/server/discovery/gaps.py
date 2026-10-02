"""SPEC-12 §2 · F-D11 内容缺口分析：订阅信号（竞品在写）vs 本方产出（我在写）→ AI 找蓝海。

诚实边界（SPEC-12 §0 D3）：没有任何订阅条目时返回
``{insufficient: true, ...}`` **不调模型**。需求侧信号由代码统计——
订阅关键词命中数 + 标题高频二元组（无分词库，二元组是诚实的近似并在
notice 里说明），供给侧同样按关键词统计本方 topics/publish_drafts；
AI 只解读数字、给方向，不许自编数据。结论不落库（即席咨询）。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from atelier.server.core import db
from atelier.server.topics import service as topic_service

from . import service

__all__ = ["WINDOW_DAYS", "collect_stats", "run_gaps"]

WINDOW_DAYS = 14
#: 高频二元组取前 N 个作为补充信号
TOP_BIGRAMS = 10

_PROMPT = """你在为社交媒体创作者做内容缺口分析：找出「高需求低竞争」的选题方向。**以下统计全部来自真实数据，只解读、不许编造或修改任何数字。**

## 需求侧（竞品/同行在写什么，近 {window} 天订阅内容统计）

- 订阅关键词命中条数：{keyword_counts}
- 标题高频词（二元组近似，无分词库）：{bigram_counts}

## 供给侧（我自己已有/在写什么）

- 选题池标题：{topics}
- 草稿标题：{drafts}
- 供给侧关键词覆盖：{my_counts}

## 你的任务

输出严格 JSON，不要输出 JSON 以外的任何文字：

```json
{{"gaps": [{{"direction": "缺口方向(2~60字)", "demand": "需求依据(引用上面的数字,2~80字)", "evidence": "竞争空白依据(对照供给侧,2~80字)", "action": "下一步动作(2~80字)"}}]}}
```

gaps 数组 1~6 条，按「需求高、供给空白」程度从高到低排。证据必须引用给出的真实数字。"""


def _bigrams(texts: list[str]) -> Counter[str]:
    """中文二元组频次（无分词库的诚实近似）：过滤标点/空白与单字符。"""
    counter: Counter[str] = Counter()
    for t in texts:
        cleaned = re.sub(r"[\s\d\W]+", "", t.lower())
        for i in range(len(cleaned) - 1):
            counter[cleaned[i : i + 2]] += 1
    return counter


def collect_stats(*, window_days: int = WINDOW_DAYS) -> dict[str, Any]:
    """聚合需求/供给侧统计（代码持有，AI 只解读，SPEC-12 §0 D3）。"""
    from datetime import UTC, datetime, timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=window_days)).isoformat(timespec="seconds")
    with db.db_session(commit=False) as conn:
        feed_rows = conn.execute(
            "SELECT fi.title, fi.summary, s.keywords FROM feed_items fi"
            " JOIN subscriptions s ON s.id = fi.subscription_id"
            " WHERE COALESCE(fi.published_at, fi.fetched_at) >= ?",
            (cutoff,),
        ).fetchall()
        topic_rows = conn.execute("SELECT title FROM topics ORDER BY updated_at DESC LIMIT 100").fetchall()
        draft_rows = conn.execute(
            "SELECT title FROM publish_drafts WHERE title != '' ORDER BY updated_at DESC LIMIT 100"
        ).fetchall()

    keyword_counts: Counter[str] = Counter()
    titles: list[str] = []
    for r in feed_rows:
        titles.append(f"{r['title']} {r['summary'] or ''}")
        for kw in service.parse_keywords(r["keywords"]):
            if kw in r["title"] or kw in (r["summary"] or ""):
                keyword_counts[kw] += 1

    my_titles = [r["title"] for r in topic_rows]
    draft_titles = [r["title"] for r in draft_rows]
    my_vocab = sorted({kw for r in feed_rows for kw in service.parse_keywords(r["keywords"])})
    my_counts = {kw: sum(1 for t in my_titles + draft_titles if kw in t) for kw in my_vocab}

    return {
        "window_days": window_days,
        "feed_total": len(feed_rows),
        "keyword_counts": dict(keyword_counts.most_common(15)),
        "bigram_counts": dict(_bigrams(titles).most_common(TOP_BIGRAMS)),
        "topic_titles": my_titles[:20],
        "draft_titles": draft_titles[:20],
        "my_counts": my_counts,
    }


def _validate_gaps(data: Any) -> list[dict[str, str]]:
    """严格 JSON 契约（SPEC-12 §2）：gaps 1..6 条、四个字段各 2..80 字。"""
    if not isinstance(data, dict) or not isinstance(data.get("gaps"), list) or not data["gaps"]:
        raise topic_service.AIOutputInvalid(
            "内容缺口输出缺少 gaps 数组", detail={"got": str(data)[:200]}
        )
    gaps = data["gaps"]
    if len(gaps) > 6:
        raise topic_service.AIOutputInvalid(
            f"gaps 返回 {len(gaps)} 条，超过上限 6", detail={"count": len(gaps)}
        )
    out: list[dict[str, str]] = []
    for g in gaps:
        if not isinstance(g, dict):
            raise topic_service.AIOutputInvalid("gaps 项不是对象", detail={"item": str(g)[:120]})
        row: dict[str, str] = {}
        for field in ("direction", "demand", "evidence", "action"):
            v = g.get(field)
            if not isinstance(v, str) or len(v.strip()) < 2:
                raise topic_service.AIOutputInvalid(
                    f"gaps 项缺字段 {field} 或过短", detail={"field": field, "item": str(g)[:120]}
                )
            v = v.strip()
            if len(v) > 80:
                raise topic_service.AIOutputInvalid(
                    f"gaps.{field} 超过 80 字（当前 {len(v)} 字）", detail={"field": field}
                )
            row[field] = v
        out.append(row)
    return out


async def run_gaps(*, profile_id: str | None = None, window_days: int = WINDOW_DAYS) -> dict[str, Any]:
    stats = collect_stats(window_days=window_days)
    if stats["feed_total"] == 0:
        return {
            "insufficient": True,
            "need": 1,
            "stats": stats,
            "message": (
                f"近 {window_days} 天订阅内容为 0 条——先添加订阅并抓取（或手填条目），"
                "没有竞品信号算不出缺口，不编造结论"
            ),
        }
    prompt = _PROMPT.format(
        window=window_days,
        keyword_counts=json.dumps(stats["keyword_counts"], ensure_ascii=False) or "（无）",
        bigram_counts=json.dumps(stats["bigram_counts"], ensure_ascii=False) or "（无）",
        topics="；".join(stats["topic_titles"]) or "（空）",
        drafts="；".join(stats["draft_titles"]) or "（空）",
        my_counts=json.dumps(stats["my_counts"], ensure_ascii=False) or "（无）",
    )
    raw = await topic_service.run_ai_text(
        domain="discovery", task="gaps", prompt=prompt, profile_id=profile_id
    )
    data = topic_service.extract_json(raw, task="gaps")
    gaps = _validate_gaps(data)
    serialized = json.dumps({"gaps": gaps}, ensure_ascii=False)
    gate_report = topic_service.gates_block_or_raise(serialized, what="内容缺口分析")
    return {
        "insufficient": False,
        "gaps": gaps,
        "stats": stats,
        "notice": "标题高频词是二元组近似（未引入分词库）；结论基于订阅信号，供参考",
        "gate_report": gate_report,
    }
