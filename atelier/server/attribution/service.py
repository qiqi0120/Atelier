"""SPEC-15 · 归因域服务层：快照 / 表现 / ROI 的 CRUD、代码聚合与域错误。

**诚实原则是本域的存在前提**（SPEC-15 §0 D1）：

- 平台数据**不可自动抓取**（无公开 API），三张表全部由用户手工录入；
- 增长对比 / ROI 汇总 / 看板聚合全部由 SQL + 代码相减/求和，不调模型、不编数字；
- 数据不足的端点返回 ``{insufficient: true, need, message}``，与 SPEC-11/12 同语义；
- AI 任务在 :mod:`.insights`，只解读本模块算出的统计。

行转换沿用 discovery 的「每张表唯一出口」约定；域内新错误只有
``AttributionIncomplete``（AI Markdown 缺段，422），不动 ``errors.py``。
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from atelier.server.core import db
from atelier.server.errors import AtelierError, NotFound, ValidationError
from atelier.server.profile import store as profile_store

__all__ = [
    "PLATFORM_MAX",
    "RECORDS_FOR_REVIEW",
    "RECORDS_FOR_STRATEGY",
    "SEDIMENT_MAX",
    "AttributionIncomplete",
    "collect_review_stats",
    "create_metric",
    "create_roi",
    "create_snapshot",
    "dashboard",
    "delete_snapshot",
    "growth",
    "list_metrics",
    "list_snapshots",
    "records_recent",
    "roi_summary",
    "row_to_metric",
    "row_to_roi",
    "row_to_snapshot",
    "sediment_memory",
    "strategy_stats",
    "validate_iso_date",
    "validate_platform",
    "workbench_summary",
]

PLATFORM_MAX = 40
NOTE_MAX = 500
PROJECT_MAX = 80
SEDIMENT_MAX = 500

#: F-G33 复盘 / F-G36 策略的最低数据门槛（SPEC-15 §2，不足不调模型）
RECORDS_FOR_REVIEW = 5
RECORDS_FOR_STRATEGY = 3


class AttributionIncomplete(AtelierError):
    """AI 复盘/策略缺段（SPEC-15 §0 D4）。缺段如实报错，不硬编补齐。"""

    code = "AttributionIncomplete"
    http = 422
    default_message = "归因结果不完整：缺少规定的段落"
    default_hint = "重试一次；连续失败就换模型或把统计窗口缩小"


# ---------------------------------------------------------------------------
# 校验助手
# ---------------------------------------------------------------------------


def validate_platform(value: Any) -> str:
    """platform 必填 1..40 字（快照/表现共用的口径）。"""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("platform 不能为空", hint="填平台标识，如 xhs / dy / gzh")
    p = value.strip()
    if len(p) > PLATFORM_MAX:
        raise ValidationError(
            f"platform 最长 {PLATFORM_MAX} 字（当前 {len(p)} 字）", detail={"max": PLATFORM_MAX}
        )
    return p


def validate_iso_date(value: Any, *, label: str, allow_empty: bool = False) -> str:
    """``YYYY-MM-DD`` 零填充完整格式（与 discovery/service.validate_iso_date 同口径）。

    ``2026-1-2`` 这类宽松写法按非法处理，保证可比、可排序；缺省给今天。
    """
    if value is None or value == "":
        if allow_empty:
            return ""
        raise ValidationError(f"{label} 不能为空", detail={"field": label})
    if not isinstance(value, str):
        raise ValidationError(f"{label} 必须是 YYYY-MM-DD 格式的字符串", detail={"field": label})
    v = value.strip()
    try:
        parsed = datetime.fromisoformat(v)
    except ValueError as exc:
        raise ValidationError(
            f"{label} 不是合法日期", detail={"field": label, "got": v}, hint="格式：YYYY-MM-DD"
        ) from exc
    if parsed.date().isoformat() != v:
        raise ValidationError(f"{label} 必须是零填充的 YYYY-MM-DD", detail={"field": label, "got": v})
    return v


def _count(value: Any, *, label: str) -> int:
    """非负整数（bool 刻意排除——True 不是计数）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{label} 必须是非负整数", detail={"field": label, "got": str(value)[:60]})
    if isinstance(value, float) and not value.is_integer():
        raise ValidationError(f"{label} 必须是整数", detail={"field": label, "got": value})
    iv = int(value)
    if iv < 0:
        raise ValidationError(f"{label} 不能为负数", detail={"field": label, "got": iv},
                              hint="计数没有负数；想清零就填 0")
    return iv


def _nonneg_number(value: Any, *, label: str) -> float:
    """非负数（ROI 的 hours/amount 用）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{label} 必须是数字", detail={"field": label, "got": str(value)[:60]})
    f = float(value)
    if f < 0:
        raise ValidationError(f"{label} 不能为负数", detail={"field": label, "got": value})
    return f


def _validate_days(days: Any, *, default: int = 0) -> int:
    if days is None or days == "":
        return default
    d = _count(days, label="days")
    if d > 3650:
        raise ValidationError("days 取值 0..3650", detail={"days": d})
    return d


def _short(value: Any, *, label: str, max_len: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"{label} 必须是字符串", detail={"field": label})
    v = value.strip()
    if len(v) > max_len:
        raise ValidationError(f"{label} 最长 {max_len} 字（当前 {len(v)} 字）", detail={"max": max_len})
    return v


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


# ---------------------------------------------------------------------------
# 行转换（每张表唯一出口）
# ---------------------------------------------------------------------------


def row_to_snapshot(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "platform": row["platform"],
        "captured_at": row["captured_at"],
        "followers": row["followers"] or 0,
        "likes_total": row["likes_total"] or 0,
        "works_total": row["works_total"] or 0,
        "note": row["note"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_metric(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "record_id": row["record_id"],
        "platform": row["platform"],
        "views": row["views"] or 0,
        "likes": row["likes"] or 0,
        "comments": row["comments"] or 0,
        "shares": row["shares"] or 0,
        "collected_at": row["collected_at"],
        "note": row["note"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_roi(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "record_id": row["record_id"] or "",
        "project": row["project"] or "",
        "hours": row["hours"] or 0,
        "amount": row["amount"] or 0,
        "note": row["note"] or "",
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------------------
# 账号快照（F-G30 的原始数据）
# ---------------------------------------------------------------------------


def list_snapshots(*, platform: str = "") -> dict[str, Any]:
    sql = "SELECT * FROM account_snapshots WHERE 1=1"
    args: list[Any] = []
    if platform:
        sql += " AND platform = ?"
        args.append(platform)
    sql += " ORDER BY captured_at DESC, created_at DESC"
    with db.db_session(commit=False) as conn:
        rows = conn.execute(sql, args).fetchall()
    items = [row_to_snapshot(r) for r in rows]
    return {"items": items, "total": len(items)}


def create_snapshot(
    *,
    platform: str,
    captured_at: str = "",
    followers: int = 0,
    likes_total: int = 0,
    works_total: int = 0,
    note: str = "",
) -> dict[str, Any]:
    p = validate_platform(platform)
    d = validate_iso_date(captured_at or _today(), label="captured_at")
    counts = {
        "followers": _count(followers, label="followers"),
        "likes_total": _count(likes_total, label="likes_total"),
        "works_total": _count(works_total, label="works_total"),
    }
    sid = f"snap-{uuid.uuid4().hex[:16]}"
    now = db.utcnow()
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO account_snapshots (id, platform, captured_at, followers, likes_total,"
            " works_total, note, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (sid, p, d, counts["followers"], counts["likes_total"], counts["works_total"],
             _short(note, label="note", max_len=NOTE_MAX), now, now),
        )
    with db.db_session(commit=False) as conn:
        row = conn.execute("SELECT * FROM account_snapshots WHERE id = ?", (sid,)).fetchone()
    return row_to_snapshot(row)


def delete_snapshot(snapshot_id: str) -> dict[str, Any]:
    with db.db_session(commit=False) as conn:
        row = conn.execute("SELECT 1 FROM account_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    if row is None:
        raise NotFound("快照不存在", detail={"snapshot_id": snapshot_id}, hint="可能已删除，刷新列表看看")
    with db.db_session() as conn:
        conn.execute("DELETE FROM account_snapshots WHERE id = ?", (snapshot_id,))
    return {"ok": True, "id": snapshot_id}


def growth(*, platform: str, days: int = 0) -> dict[str, Any]:
    """F-G30 增长对比：该平台最近两条快照的差值，**代码相减，不调模型**。

    ``days > 0`` 时只看窗口内的快照；不足两条 → insufficient（SPEC-15 §0 D7）。
    """
    p = validate_platform(platform)
    d = _validate_days(days)
    today = _today()
    cutoff = (datetime.fromisoformat(f"{today}T00:00:00") - timedelta(days=d)).date().isoformat() if d else ""
    sql = "SELECT * FROM account_snapshots WHERE platform = ?"
    args: list[Any] = [p]
    if cutoff:
        sql += " AND captured_at >= ?"
        args.append(cutoff)
    sql += " ORDER BY captured_at DESC, created_at DESC LIMIT 2"
    with db.db_session(commit=False) as conn:
        rows = conn.execute(sql, args).fetchall()
    if len(rows) < 2:
        return {
            "insufficient": True,
            "need": 2,
            "have": len(rows),
            "message": (
                f"「{p}」至少要有 2 条快照才能算增长（当前 {len(rows)} 条）"
                "——增长对比只做真实差值，不编数字"
            ),
        }
    current, previous = row_to_snapshot(rows[0]), row_to_snapshot(rows[1])
    delta = {k: current[k] - previous[k] for k in ("followers", "likes_total", "works_total")}
    window = (
        datetime.fromisoformat(current["captured_at"]).date()
        - datetime.fromisoformat(previous["captured_at"]).date()
    ).days
    return {
        "insufficient": False,
        "current": current,
        "previous": previous,
        "delta": delta,
        "window_days": window,
        "platform": p,
    }


# ---------------------------------------------------------------------------
# 内容表现（F-G31）
# ---------------------------------------------------------------------------


def create_metric(
    *,
    record_id: str,
    platform: str,
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    shares: int = 0,
    collected_at: str = "",
    note: str = "",
) -> dict[str, Any]:
    """单条内容表现录入。record 必须存在（404）；platform 必须与 record 一致（422）。"""
    if not isinstance(record_id, str) or not record_id.strip():
        raise ValidationError("record_id 不能为空", hint="从发布记录里选一条要回填表现的记录")
    with db.db_session(commit=False) as conn:
        record = conn.execute(
            "SELECT id, platform FROM publish_records WHERE id = ?", (record_id,)
        ).fetchone()
    if record is None:
        raise NotFound(
            "发布记录不存在",
            detail={"record_id": record_id},
            hint="先发布（dry-run 也算）拿到记录，再回填表现数据",
        )
    p = validate_platform(platform)
    if p != record["platform"]:
        raise ValidationError(
            "platform 与该发布记录的平台不一致",
            detail={"record_platform": record["platform"], "got": p},
            hint="表现数据必须挂在同一条平台记录上；换平台请另发一条",
        )
    counts = {
        "views": _count(views, label="views"),
        "likes": _count(likes, label="likes"),
        "comments": _count(comments, label="comments"),
        "shares": _count(shares, label="shares"),
    }
    d = validate_iso_date(collected_at or _today(), label="collected_at")
    mid = f"met-{uuid.uuid4().hex[:16]}"
    now = db.utcnow()
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO content_metrics (id, record_id, platform, views, likes, comments,"
            " shares, collected_at, note, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (mid, record["id"], p, counts["views"], counts["likes"], counts["comments"],
             counts["shares"], d, _short(note, label="note", max_len=NOTE_MAX), now, now),
        )
    with db.db_session(commit=False) as conn:
        row = conn.execute("SELECT * FROM content_metrics WHERE id = ?", (mid,)).fetchone()
    return row_to_metric(row)


def list_metrics(*, platform: str = "", days: int = 0) -> dict[str, Any]:
    """列表 + 代码聚合（``days=0`` 表示不设窗口）。聚合数字全部来自现查行。"""
    d = _validate_days(days)
    cutoff = (
        (datetime.now(UTC) - timedelta(days=d)).date().isoformat() if d else ""
    )
    sql = "SELECT * FROM content_metrics WHERE 1=1"
    args: list[Any] = []
    if platform:
        sql += " AND platform = ?"
        args.append(platform)
    if cutoff:
        sql += " AND collected_at >= ?"
        args.append(cutoff)
    sql += " ORDER BY collected_at DESC, created_at DESC"
    with db.db_session(commit=False) as conn:
        rows = conn.execute(sql, args).fetchall()
    items = [row_to_metric(r) for r in rows]
    agg = {
        "total_views": sum(i["views"] for i in items),
        "total_likes": sum(i["likes"] for i in items),
        "total_comments": sum(i["comments"] for i in items),
        "total_shares": sum(i["shares"] for i in items),
    }
    agg["avg_views"] = round(agg["total_views"] / len(items), 1) if items else 0
    return {"items": items, "total": len(items), "agg": agg, "days": d}


# ---------------------------------------------------------------------------
# ROI（F-G34）
# ---------------------------------------------------------------------------


def create_roi(
    *,
    hours: float = 0,
    amount: float = 0,
    record_id: str = "",
    project: str = "",
    note: str = "",
) -> dict[str, Any]:
    """投入台账录入。hours/amount ≥ 0，且至少一项 > 0（否则记台账没有意义）。"""
    h = _nonneg_number(hours, label="hours")
    a = _nonneg_number(amount, label="amount")
    if h == 0 and a == 0:
        raise ValidationError(
            "hours 与 amount 至少一项大于 0",
            hint="只花时间就填 hours；只花钱就填 amount",
        )
    rid = f"roi-{uuid.uuid4().hex[:16]}"
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO roi_entries (id, record_id, project, hours, amount, note, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (rid, _short(record_id, label="record_id", max_len=80),
             _short(project, label="project", max_len=PROJECT_MAX), h, a,
             _short(note, label="note", max_len=NOTE_MAX), db.utcnow()),
        )
    with db.db_session(commit=False) as conn:
        row = conn.execute("SELECT * FROM roi_entries WHERE id = ?", (rid,)).fetchone()
    return row_to_roi(row)


def roi_summary(*, days: int = 30) -> dict[str, Any]:
    """投入合计 + 同期内容产出合计，全部代码相加。无投入记录 → insufficient。"""
    d = _validate_days(days, default=30)
    cutoff_dt = (datetime.now(UTC) - timedelta(days=d)).isoformat(timespec="seconds")
    cutoff_date = (datetime.now(UTC) - timedelta(days=d)).date().isoformat()
    with db.db_session(commit=False) as conn:
        roi_rows = conn.execute(
            "SELECT hours, amount FROM roi_entries WHERE created_at >= ?", (cutoff_dt,)
        ).fetchall()
    if not roi_rows:
        return {
            "insufficient": True,
            "need": 1,
            "stats": {"roi_entries": 0},
            "message": f"近 {d} 天还没有投入记录——ROI 只算真实台账，不编产出比",
        }
    with db.db_session(commit=False) as conn:
        met_rows = conn.execute(
            "SELECT views, likes, comments, shares FROM content_metrics WHERE collected_at >= ?",
            (cutoff_date,),
        ).fetchall()
    total_hours = round(sum(r["hours"] or 0 for r in roi_rows), 2)
    total_amount = round(sum(r["amount"] or 0 for r in roi_rows), 2)
    output = {
        "total_views": sum(r["views"] or 0 for r in met_rows),
        "total_likes": sum(r["likes"] or 0 for r in met_rows),
        "total_comments": sum(r["comments"] or 0 for r in met_rows),
        "total_shares": sum(r["shares"] or 0 for r in met_rows),
    }
    roi_hint = (
        f"近 {d} 天投入 {total_hours:g} 小时 / {total_amount:g} 元，"
        f"同期 {len(met_rows)} 条内容产出 {output['total_views']} 曝光 / {output['total_likes']} 赞；"
        "以上全部来自你的手工录入，只做合计，不构成收益推断"
    )
    return {
        "insufficient": False,
        "days": d,
        "total_hours": total_hours,
        "total_amount": total_amount,
        "content_count": len(met_rows),
        "output": output,
        "roi_hint": roi_hint,
    }


# ---------------------------------------------------------------------------
# 本地统计聚合（复盘 / 策略 / 工作台 / 看板的数据源，全部代码持有）
# ---------------------------------------------------------------------------


def collect_review_stats(today: datetime | None = None) -> dict[str, Any]:
    """F-G33 复盘的客观统计（近 30 天记录/平台分布 + 表现聚合 + 选题流转）。"""
    today = today or datetime.now(UTC)
    cutoff_dt = (today - timedelta(days=30)).isoformat(timespec="seconds")
    cutoff_date = (today - timedelta(days=30)).date().isoformat()
    with db.db_session(commit=False) as conn:
        total = conn.execute("SELECT COUNT(*) FROM publish_records").fetchone()[0]
        last30 = conn.execute(
            "SELECT COUNT(*) FROM publish_records WHERE created_at >= ?", (cutoff_dt,)
        ).fetchone()[0]
        by_platform = {
            r["platform"]: r["n"]
            for r in conn.execute(
                "SELECT platform, COUNT(*) AS n FROM publish_records GROUP BY platform ORDER BY n DESC"
            ).fetchall()
        }
        met = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(views),0) AS v, COALESCE(SUM(likes),0) AS l,"
            " COALESCE(SUM(comments),0) AS c, COALESCE(SUM(shares),0) AS s"
            " FROM content_metrics WHERE collected_at >= ?",
            (cutoff_date,),
        ).fetchone()
        topic_rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM topics GROUP BY status"
        ).fetchall()
        recent = [
            r["title"] or "（无标题）"
            for r in conn.execute(
                "SELECT title FROM publish_records ORDER BY created_at DESC LIMIT 8"
            ).fetchall()
        ]
    topics_flow = {s: 0 for s in ("todo", "doing", "done")}
    for r in topic_rows:
        if r["status"] in topics_flow:
            topics_flow[r["status"]] = r["n"]
    return {
        "records_total": total,
        "records_last_30d": last30,
        "by_platform": by_platform,
        "metrics_last_30d": {
            "count": met["n"],
            "total_views": met["v"],
            "total_likes": met["l"],
            "total_comments": met["c"],
            "total_shares": met["s"],
        },
        "topics_flow": topics_flow,
        "recent_titles": recent,
    }


def strategy_stats(today: datetime | None = None) -> dict[str, Any]:
    """F-G36 策略的历史聚合：全量表现实测 + 表现最佳平台（按总曝光，代码判定）。"""
    today = today or datetime.now(UTC)
    cutoff_date = (today - timedelta(days=90)).date().isoformat()
    with db.db_session(commit=False) as conn:
        records_total = conn.execute("SELECT COUNT(*) FROM publish_records").fetchone()[0]
        metrics_total = conn.execute("SELECT COUNT(*) FROM content_metrics").fetchone()[0]
        by_platform = [
            {
                "platform": r["platform"],
                "count": r["n"],
                "total_views": r["v"],
                "total_likes": r["l"],
                "total_comments": r["c"],
                "total_shares": r["s"],
            }
            for r in conn.execute(
                "SELECT platform, COUNT(*) AS n, COALESCE(SUM(views),0) AS v,"
                " COALESCE(SUM(likes),0) AS l, COALESCE(SUM(comments),0) AS c,"
                " COALESCE(SUM(shares),0) AS s FROM content_metrics GROUP BY platform"
            ).fetchall()
        ]
        recent = [
            r["title"] or "（无标题）"
            for r in conn.execute(
                "SELECT title FROM publish_records WHERE created_at >= ?"
                " ORDER BY created_at DESC LIMIT 8",
                ((today - timedelta(days=90)).isoformat(timespec="seconds"),),
            ).fetchall()
        ]
    best = max(by_platform, key=lambda x: (x["total_views"], x["count"]), default=None)
    return {
        "records_total": records_total,
        "metrics_total": metrics_total,
        "metrics_by_platform": by_platform,
        "best_platform_by_views": best["platform"] if best else "",
        "window_days": 90,
        "window_since": cutoff_date,
        "recent_titles": recent,
    }


def _todo_items(conn: sqlite3.Connection, today_date: str) -> list[dict[str, str]]:
    """F-H1 今日待办：四类各取前 3（SQL 现查，谓词与上方计数完全一致）。

    组序固定：待发草稿（scheduled_date 升序）→ doing 选题 → 今日日历 → 待处理热点；
    全空返回空数组，不编条目。
    """
    untitled = "COALESCE(NULLIF(title,''),'（无标题）')"
    drafts = conn.execute(
        f"SELECT {untitled} AS t FROM publish_drafts d"
        " WHERE COALESCE(d.scheduled_date,'') != ''"
        " AND NOT EXISTS (SELECT 1 FROM publish_records pr WHERE pr.draft_id = d.id"
        " AND pr.status = 'sent')"
        " ORDER BY d.scheduled_date ASC, d.created_at ASC LIMIT 3"
    ).fetchall()
    doing = conn.execute(
        f"SELECT {untitled} AS t FROM topics WHERE status = 'doing'"
        " ORDER BY updated_at DESC, created_at DESC LIMIT 3"
    ).fetchall()
    events = conn.execute(
        "SELECT title AS t FROM calendar_events WHERE date <= ?"
        " AND COALESCE(NULLIF(end_date,''), date) >= ?"
        " ORDER BY date ASC, created_at ASC LIMIT 3",
        (today_date, today_date),
    ).fetchall()
    hots = conn.execute(
        "SELECT title AS t FROM hot_entries WHERE status = 'pending'"
        " ORDER BY created_at ASC, id ASC LIMIT 3"
    ).fetchall()
    return (
        [{"kind": "draft", "title": r["t"], "to": "/publish"} for r in drafts]
        + [{"kind": "topic", "title": r["t"], "to": "/topics"} for r in doing]
        + [{"kind": "calendar", "title": r["t"], "to": "/calendar"} for r in events]
        + [{"kind": "hot", "title": r["t"], "to": "/hot"} for r in hots]
    )


def workbench_summary(today: datetime | None = None) -> dict[str, Any]:
    """F-H1 工作台概览数据源：全部 SQL 现查，**不许写死数字**（SPEC-15 §2）。

    scheduler 字段直接 import ``publish.scheduler.get_status()``，口径只有一份。
    """
    today = today or datetime.now(UTC)
    today_date = today.date().isoformat()
    cutoff7 = (today - timedelta(days=7)).isoformat(timespec="seconds")
    with db.db_session(commit=False) as conn:
        topics = {s: 0 for s in ("todo", "doing", "done")}
        for r in conn.execute("SELECT status, COUNT(*) AS n FROM topics GROUP BY status"):
            if r["status"] in topics:
                topics[r["status"]] = r["n"]
        drafts_pending = conn.execute(
            "SELECT COUNT(*) FROM publish_drafts d WHERE COALESCE(d.scheduled_date,'') != ''"
            " AND NOT EXISTS (SELECT 1 FROM publish_records pr WHERE pr.draft_id = d.id"
            " AND pr.status = 'sent')"
        ).fetchone()[0]
        calendar_today = conn.execute(
            "SELECT COUNT(*) FROM calendar_events WHERE date <= ?"
            " AND COALESCE(NULLIF(end_date,''), date) >= ?",
            (today_date, today_date),
        ).fetchone()[0]
        hot_pending = conn.execute(
            "SELECT COUNT(*) FROM hot_entries WHERE status = 'pending'"
        ).fetchone()[0]
        artifacts_7d = conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE created_at >= ?", (cutoff7,)
        ).fetchone()[0]
        records_7d = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM publish_records WHERE created_at >= ?"
                " AND status IN ('sent','failed') GROUP BY status",
                (cutoff7,),
            ).fetchall()
        }
        todo_items = _todo_items(conn, today_date)
    from ..publish import scheduler

    return {
        "topics": topics,
        "drafts_pending": drafts_pending,
        "calendar_today": calendar_today,
        "hot_pending": hot_pending,
        "artifacts_last_7d": artifacts_7d,
        "records_last_7d": {
            "sent": records_7d.get("sent", 0),
            "failed": records_7d.get("failed", 0),
        },
        "scheduler": scheduler.get_status(),
        "todo_items": todo_items,
        "as_of": db.utcnow(),
    }


def records_recent(*, limit: int = 20) -> dict[str, Any]:
    """表现录入下拉的数据源：最近 20 条发布记录左联草稿取标题（F-G31 录入辅助）。

    草稿可不存在（dry-run 记录也允许先于草稿存在），``draft_title`` 缺省为空串。
    """
    n = _count(limit, label="limit")
    if not 1 <= n <= 100:
        raise ValidationError("limit 取值 1..100", detail={"limit": n})
    with db.db_session(commit=False) as conn:
        rows = conn.execute(
            "SELECT pr.id, pr.platform, pr.title, pr.created_at,"
            " COALESCE(pd.title,'') AS draft_title FROM publish_records pr"
            " LEFT JOIN publish_drafts pd ON pd.id = pr.draft_id"
            " ORDER BY pr.created_at DESC, pr.id DESC LIMIT ?",
            (n,),
        ).fetchall()
    return {
        "items": [
            {
                "id": r["id"],
                "platform": r["platform"],
                "title": r["title"] or "",
                "created_at": r["created_at"],
                "draft_title": r["draft_title"],
            }
            for r in rows
        ],
        "total": len(rows),
    }


def dashboard(*, platform: str = "", days: int = 30) -> dict[str, Any]:
    """F-H2 数据看板数据源：快照曲线 + 表现按天聚合 + Top 内容。

    无快照且无表现数据 → ``insufficient: true + message``（前端渲染空态，
    不得自造数字，SPEC-15 §0 D7）。
    """
    d = _validate_days(days, default=30)
    cutoff = (datetime.now(UTC) - timedelta(days=d)).date().isoformat()
    sql_snap = (
        "SELECT captured_at, followers FROM account_snapshots WHERE captured_at >= ?"
    )
    sql_met = (
        "SELECT collected_at, COALESCE(SUM(views),0) AS views, COALESCE(SUM(likes),0) AS likes,"
        " COALESCE(SUM(comments),0) AS comments, COALESCE(SUM(shares),0) AS shares"
        " FROM content_metrics WHERE collected_at >= ?"
    )
    args_snap: list[Any] = [cutoff]
    args_met: list[Any] = [cutoff]
    if platform:
        sql_snap += " AND platform = ?"
        args_snap.append(platform)
        sql_met += " AND platform = ?"
        args_met.append(platform)
    sql_snap += " ORDER BY captured_at ASC"
    sql_met += " GROUP BY collected_at ORDER BY collected_at ASC"
    with db.db_session(commit=False) as conn:
        snapshots = [
            {"captured_at": r["captured_at"], "followers": r["followers"] or 0}
            for r in conn.execute(sql_snap, args_snap).fetchall()
        ]
        metrics_by_day = [
            {
                "collected_at": r["collected_at"],
                "views": r["views"],
                "likes": r["likes"],
                "comments": r["comments"],
                "shares": r["shares"],
            }
            for r in conn.execute(sql_met, args_met).fetchall()
        ]
        top_sql = (
            "SELECT COALESCE(pr.title, '（无标题）') AS title, m.platform,"
            " SUM(m.views) AS views, SUM(m.likes) AS likes FROM content_metrics m"
            " JOIN publish_records pr ON pr.id = m.record_id WHERE m.collected_at >= ?"
        )
        args_top: list[Any] = [cutoff]
        if platform:
            top_sql += " AND m.platform = ?"
            args_top.append(platform)
        top_sql += " GROUP BY m.record_id ORDER BY views DESC LIMIT 5"
        top_contents = [
            {
                "title": r["title"],
                "platform": r["platform"],
                "views": r["views"],
                "likes": r["likes"],
            }
            for r in conn.execute(top_sql, args_top).fetchall()
        ]
    out: dict[str, Any] = {
        "platform": platform,
        "days": d,
        "snapshots": snapshots,
        "metrics_by_day": metrics_by_day,
        "top_contents": top_contents,
    }
    if not snapshots and not metrics_by_day:
        out["insufficient"] = True
        out["message"] = (
            f"{'该平台' if platform else '全部平台'}近 {d} 天还没有快照或表现数据——"
            "看板只画真实录入的数据"
        )
    else:
        out["insufficient"] = False
    return out


# ---------------------------------------------------------------------------
# 复盘沉淀（F-G33 → 画像长期记忆）
# ---------------------------------------------------------------------------


def extract_sediment_text(markdown: str) -> str:
    """取「下一步」段之前的要点，压成一句话并截断（SPEC-15 §0 D5）。"""
    m = re.search(r"^##.*下一步.*$", markdown, re.MULTILINE)
    head = markdown[: m.start()] if m else markdown
    lines = [ln.lstrip("# ").strip() for ln in head.splitlines()]
    text = "；".join(ln for ln in lines if ln)
    return text[:SEDIMENT_MAX]


def sediment_memory(profile_id: str, text: str) -> dict[str, Any]:
    """把复盘要点写进画像长期记忆（``profile.store.add_memory`` 是唯一出口）。"""
    memory = profile_store.add_memory(
        profile_id, extract_sediment_text(text), source="复盘沉淀"
    )
    return {"sedimented": True, "memory_id": memory.id}
