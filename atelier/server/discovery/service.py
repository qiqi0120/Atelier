"""发现域服务层（SPEC-12 · M2-3b）：订阅 / 热点素材池 / 算法追踪 / UGC 的 CRUD 与查询。

职责边界：

- **订阅与素材的持久化**在这里读写（schema v6 五张表，SPEC-12 §1）；
  RSS 拉取与解析在 :mod:`rss`，AI 日报在 :mod:`digest`，内容缺口在 :mod:`gaps`。
- **去重与过滤是代码事实**（SPEC-12 §0 D4）：``(subscription_id, dedup_key)``
  唯一索引 + ``INSERT OR IGNORE``，关键词/时间窗过滤在 SQL/代码层，不信任模型。
- 域内新错误只两个（不新增 errors.py 项，同 SPEC-11 先例）：
  ``DiscoveryFetchFailed``（抓取/解析失败的明确原因）、``DiscoveryIncomplete``
  （AI 日报缺段）。
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from atelier.server.core import db
from atelier.server.errors import AtelierError, NotFound, ValidationError

__all__ = [
    "HOT_SOURCE_VALUES",
    "HOT_STATUS_VALUES",
    "KIND_VALUES",
    "SUB_SOURCE_VALUES",
    "TITLE_MAX",
    "DiscoveryFetchFailed",
    "DiscoveryIncomplete",
    "create_algorithm_note",
    "create_hot_entry",
    "create_subscription",
    "delete_algorithm_note",
    "delete_subscription",
    "get_digest",
    "get_subscription",
    "hot_from_feed",
    "ingest_manual",
    "list_algorithm_notes",
    "list_digests",
    "list_feed",
    "list_hot",
    "list_subscriptions",
    "parse_keywords",
    "row_to_algorithm_note",
    "row_to_digest",
    "row_to_feed_item",
    "row_to_hot_entry",
    "row_to_subscription",
    "update_hot_entry",
    "update_subscription",
    "validate_entry_date",
    "validate_iso_date",
]

#: SPEC-12 §1 冻结枚举
KIND_VALUES: tuple[str, ...] = ("blogger", "media", "newsletter")
SUB_SOURCE_VALUES: tuple[str, ...] = ("rss", "manual")
HOT_SOURCE_VALUES: tuple[str, ...] = ("rss", "manual")
HOT_STATUS_VALUES: tuple[str, ...] = ("pending", "digested", "archived")

TITLE_MAX = 120
NOTE_MAX = 500


class DiscoveryFetchFailed(AtelierError):
    """RSS 抓取/解析失败（SPEC-12 §0 D2）。附明确原因，不做静默空结果。"""

    code = "DiscoveryFetchFailed"
    http = 422
    default_message = "订阅源抓取失败"
    default_hint = "检查 URL 是否可访问、是否为 RSS 2.0 / Atom 格式；网络恢复后重试"


class DiscoveryIncomplete(AtelierError):
    """AI 日报缺段（SPEC-12 §2）。缺段如实报错，不硬编补齐。"""

    code = "DiscoveryIncomplete"
    http = 422
    default_message = "日报结果不完整：缺少规定的段落"
    default_hint = "重试一次；连续失败就减少一次 digest 的素材量"


# ---------------------------------------------------------------------------
# 校验助手
# ---------------------------------------------------------------------------


def _validate_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("订阅名称不能为空", hint="起个能认出这个博主/媒体的名字")
    n = name.strip()
    if len(n) > TITLE_MAX:
        raise ValidationError(f"订阅名称最长 {TITLE_MAX} 字（当前 {len(n)} 字）", detail={"max": TITLE_MAX})
    return n


def validate_url(value: Any, *, required: bool = False) -> str:
    """rss 源必须给合法 http(s) URL；manual 源可空。"""
    if value is None or value == "":
        if required:
            raise ValidationError(
                "RSS 订阅必须提供 URL",
                detail={"source": "rss"},
                hint="填博主/媒体的 RSS 地址；没有 RSS 就用「手填」类型的订阅",
            )
        return ""
    if not isinstance(value, str) or not value.strip().startswith(("http://", "https://")):
        raise ValidationError(
            "URL 必须以 http:// 或 https:// 开头", detail={"url": str(value)[:120]}
        )
    v = value.strip()
    if len(v) > 2000:
        raise ValidationError("URL 过长（>2000 字符）", detail={"max": 2000})
    return v


def parse_keywords(raw: str | None) -> list[str]:
    """逗号/空格分隔 → 关键词列表（去空、去重、保序）。存库仍存原始串。"""
    if not raw:
        return []
    out: list[str] = []
    for part in raw.replace("，", ",").replace(" ", ",").split(","):
        p = part.strip()
        if p and p not in out:
            out.append(p)
    return out


def validate_iso_date(value: Any, *, label: str, allow_empty: bool = True) -> str:
    """``YYYY-MM-DD``（可空）。零填充完整格式，非法抛 ``ValidationError``。"""
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


validate_entry_date = validate_iso_date  # 别名：素材条目日期同一口径


def _validate_short(value: Any, *, label: str, max_len: int, allow_empty: bool = True) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"{label} 必须是字符串", detail={"field": label})
    v = value.strip()
    if len(v) > max_len:
        raise ValidationError(f"{label} 最长 {max_len} 字（当前 {len(v)} 字）", detail={"max": max_len})
    return v


# ---------------------------------------------------------------------------
# 行转换（每张表唯一出口）
# ---------------------------------------------------------------------------


def row_to_subscription(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "platform": row["platform"] or "",
        "kind": row["kind"],
        "source": row["source"],
        "url": row["url"] or "",
        "keywords": parse_keywords(row["keywords"]),
        "notes": row["notes"] or "",
        "enabled": bool(row["enabled"]),
        "last_fetched_at": row["last_fetched_at"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_feed_item(row: sqlite3.Row) -> dict[str, Any]:
    cols = row.keys()  # list_feed 带 JOIN 别名时才有 subscription_name
    return {
        "id": row["id"],
        "subscription_id": row["subscription_id"],
        "subscription_name": row["subscription_name"] if "subscription_name" in cols else "",
        "title": row["title"],
        "url": row["url"] or "",
        "summary": row["summary"] or "",
        "published_at": row["published_at"] or "",
        "fetched_at": row["fetched_at"],
        "dedup_key": row["dedup_key"],
    }


def row_to_hot_entry(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "source": row["source"],
        "platform": row["platform"] or "",
        "url": row["url"] or "",
        "heat": row["heat"] or "",
        "note": row["note"] or "",
        "entry_date": row["entry_date"] or "",
        "status": row["status"],
        "digest_id": row["digest_id"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_digest(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "window_start": row["window_start"] or "",
        "window_end": row["window_end"] or "",
        "markdown": row["markdown"],
        "entry_ids": db.loads(row["entry_ids"], []),
        "created_at": row["created_at"],
    }


def row_to_algorithm_note(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "platform": row["platform"],
        "noted_at": row["noted_at"],
        "change": row["change"],
        "impact": row["impact"] or "",
        "source": row["source"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# 订阅 CRUD
# ---------------------------------------------------------------------------


def list_subscriptions(
    *, kind: str = "", source: str = "", enabled: bool | None = None
) -> dict[str, Any]:
    if kind and kind not in KIND_VALUES:
        raise ValidationError(f"kind 只允许 {' / '.join(KIND_VALUES)}", detail={"kind": kind})
    if source and source not in SUB_SOURCE_VALUES:
        raise ValidationError(
            f"source 只允许 {' / '.join(SUB_SOURCE_VALUES)}", detail={"source": source}
        )
    sql = "SELECT * FROM subscriptions WHERE 1=1"
    args: list[Any] = []
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    if source:
        sql += " AND source = ?"
        args.append(source)
    if enabled is not None:
        sql += " AND enabled = ?"
        args.append(1 if enabled else 0)
    sql += " ORDER BY updated_at DESC, created_at DESC"
    with db.db_session(commit=False) as conn:
        rows = conn.execute(sql, args).fetchall()
    items = [row_to_subscription(r) for r in rows]
    return {"items": items, "total": len(items)}


def get_subscription(subscription_id: str) -> dict[str, Any]:
    with db.db_session(commit=False) as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)
        ).fetchone()
    if row is None:
        raise NotFound("订阅不存在", detail={"subscription_id": subscription_id}, hint="可能已被删除，刷新看看")
    return row_to_subscription(row)


def create_subscription(
    *,
    name: str,
    kind: str,
    source: str,
    url: str | None = None,
    platform: str = "",
    keywords: str | list[str] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    if kind not in KIND_VALUES:
        raise ValidationError(
            f"kind 只允许 {' / '.join(KIND_VALUES)}", detail={"kind": kind}, hint="博主=blogger，媒体=media，Newsletter=newsletter"
        )
    if source not in SUB_SOURCE_VALUES:
        raise ValidationError(
            f"source 只允许 {' / '.join(SUB_SOURCE_VALUES)}", detail={"source": source}
        )
    n = _validate_name(name)
    u = validate_url(url, required=(source == "rss"))
    kw = ",".join(parse_keywords(",".join(keywords) if isinstance(keywords, list) else (keywords or "")))
    plat = _validate_short(platform, label="platform", max_len=40)
    notes_v = _validate_short(notes, label="notes", max_len=NOTE_MAX)
    sid = f"sub-{uuid.uuid4().hex[:16]}"
    now = db.utcnow()
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO subscriptions (id, name, platform, kind, source, url, keywords,"
            " notes, enabled, last_fetched_at, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,1,'',?,?)",
            (sid, n, plat, kind, source, u, kw, notes_v, now, now),
        )
    return get_subscription(sid)


def update_subscription(subscription_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """PATCH 语义：字段不在请求体或显式 null = 不动；keywords 传 list/串 = 整体替换。"""
    current = get_subscription(subscription_id)
    sets: list[str] = []
    args: list[Any] = []
    if "name" in changes and changes["name"] is not None:
        sets.append("name = ?")
        args.append(_validate_name(changes["name"]))
    if "url" in changes and changes["url"] is not None:
        sets.append("url = ?")
        args.append(validate_url(changes["url"], required=(current["source"] == "rss")))
    if "platform" in changes and changes["platform"] is not None:
        sets.append("platform = ?")
        args.append(_validate_short(changes["platform"], label="platform", max_len=40))
    if "keywords" in changes and changes["keywords"] is not None:
        raw = ",".join(changes["keywords"]) if isinstance(changes["keywords"], list) else changes["keywords"]
        sets.append("keywords = ?")
        args.append(",".join(parse_keywords(raw)))
    if "notes" in changes and changes["notes"] is not None:
        sets.append("notes = ?")
        args.append(_validate_short(changes["notes"], label="notes", max_len=NOTE_MAX))
    if "enabled" in changes and changes["enabled"] is not None:
        sets.append("enabled = ?")
        args.append(1 if changes["enabled"] else 0)
    if sets:
        sets.append("updated_at = ?")
        args.append(db.utcnow())
        args.append(subscription_id)
        with db.db_session() as conn:
            conn.execute(f"UPDATE subscriptions SET {', '.join(sets)} WHERE id = ?", args)
    return current if not sets else get_subscription(subscription_id)


def delete_subscription(subscription_id: str) -> dict[str, Any]:
    get_subscription(subscription_id)  # 不存在 → 404
    with db.db_session() as conn:
        conn.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))  # feed_items 级联
    return {"ok": True, "id": subscription_id}


def touch_fetched(subscription_id: str) -> None:
    with db.db_session() as conn:
        conn.execute(
            "UPDATE subscriptions SET last_fetched_at = ?, updated_at = ? WHERE id = ?",
            (db.utcnow(), db.utcnow(), subscription_id),
        )


# ---------------------------------------------------------------------------
# feed 条目
# ---------------------------------------------------------------------------


def _insert_feed_item(
    conn: sqlite3.Connection,
    *,
    subscription_id: str,
    title: str,
    url: str,
    summary: str,
    published_at: str,
    dedup_key: str,
) -> bool:
    cur = conn.execute(
        "INSERT OR IGNORE INTO feed_items (id, subscription_id, title, url, summary,"
        " published_at, fetched_at, dedup_key) VALUES (?,?,?,?,?,?,?,?)",
        (f"feed-{uuid.uuid4().hex[:16]}", subscription_id, title, url, summary,
         published_at, db.utcnow(), dedup_key),
    )
    return cur.rowcount > 0


def ingest_manual(
    subscription_id: str,
    *,
    title: str,
    url: str = "",
    summary: str = "",
    published_at: str = "",
) -> dict[str, Any]:
    """manual 源手填条目（SPEC-12 §2）。dedup_key = title+url 哈希，重复填返回 inserted=False。"""
    sub = get_subscription(subscription_id)
    if not isinstance(title, str) or not title.strip():
        raise ValidationError("条目标题不能为空", hint="粘贴博主那条内容的标题或开头一句")
    t = title.strip()
    if len(t) > TITLE_MAX:
        raise ValidationError(f"条目标题最长 {TITLE_MAX} 字（当前 {len(t)} 字）", detail={"max": TITLE_MAX})
    u = validate_url(url)
    s = _validate_short(summary, label="summary", max_len=2000)
    import hashlib

    dedup = hashlib.sha1(f"{t}|{u}".encode()).hexdigest()
    with db.db_session() as conn:
        inserted = _insert_feed_item(
            conn, subscription_id=sub["id"], title=t, url=u, summary=s,
            published_at=validate_iso_date(published_at, label="published_at"), dedup_key=dedup,
        )
    return {"inserted": inserted, "subscription_id": sub["id"], "title": t}


def list_feed(
    *,
    subscription_id: str = "",
    q: str = "",
    days: int = 7,
    limit: int = 200,
) -> dict[str, Any]:
    """feed 列表，时间倒序；``days`` 时间窗按 COALESCE(published_at, fetched_at)（SPEC-12 §0 D4）。"""
    if days < 0 or days > 365:
        raise ValidationError("days 取值 0..365", detail={"days": days})
    if limit < 1 or limit > 500:
        raise ValidationError("limit 取值 1..500", detail={"limit": limit})
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
    sql = (
        "SELECT fi.*, s.name AS subscription_name FROM feed_items fi"
        " JOIN subscriptions s ON s.id = fi.subscription_id WHERE 1=1"
    )
    args: list[Any] = []
    if subscription_id:
        sql += " AND fi.subscription_id = ?"
        args.append(subscription_id)
    sql += " AND COALESCE(fi.published_at, fi.fetched_at) >= ?"
    args.append(cutoff)
    if q:
        sql += " AND (fi.title LIKE ? OR fi.summary LIKE ?)"
        args.extend((f"%{q}%", f"%{q}%"))
    sql += " ORDER BY COALESCE(fi.published_at, fi.fetched_at) DESC LIMIT ?"
    args.append(limit)
    with db.db_session(commit=False) as conn:
        rows = conn.execute(sql, args).fetchall()
    items = [row_to_feed_item(r) for r in rows]
    return {"items": items, "total": len(items), "days": days}


# ---------------------------------------------------------------------------
# 热点素材池
# ---------------------------------------------------------------------------


def list_hot(*, status: str = "", q: str = "", limit: int = 200) -> dict[str, Any]:
    if status and status not in HOT_STATUS_VALUES:
        raise ValidationError(
            f"status 只允许 {' / '.join(HOT_STATUS_VALUES)}", detail={"status": status}
        )
    sql = "SELECT * FROM hot_entries WHERE 1=1"
    args: list[Any] = []
    if status:
        sql += " AND status = ?"
        args.append(status)
    if q:
        sql += " AND (title LIKE ? OR note LIKE ?)"
        args.extend((f"%{q}%", f"%{q}%"))
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with db.db_session(commit=False) as conn:
        rows = conn.execute(sql, args).fetchall()
    items = [row_to_hot_entry(r) for r in rows]
    counts = {s: 0 for s in HOT_STATUS_VALUES}
    with db.db_session(commit=False) as conn:
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM hot_entries GROUP BY status"):
            counts[row["status"]] = row["n"]
    return {"items": items, "total": len(items), "counts": counts}


def create_hot_entry(
    *,
    title: str,
    source: str = "manual",
    platform: str = "",
    url: str = "",
    heat: str = "",
    note: str = "",
    entry_date: str = "",
) -> dict[str, Any]:
    if not isinstance(title, str) or not title.strip():
        raise ValidationError("热点标题不能为空", hint="粘贴那条热点在榜上的说法")
    t = title.strip()
    if len(t) > TITLE_MAX:
        raise ValidationError(f"热点标题最长 {TITLE_MAX} 字（当前 {len(t)} 字）", detail={"max": TITLE_MAX})
    if source not in HOT_SOURCE_VALUES:
        raise ValidationError(
            f"source 只允许 {' / '.join(HOT_SOURCE_VALUES)}", detail={"source": source}
        )
    hid = f"hot-{uuid.uuid4().hex[:16]}"
    now = db.utcnow()
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO hot_entries (id, title, source, platform, url, heat, note,"
            " entry_date, status, digest_id, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,'pending','',?,?)",
            (hid, t, source, _validate_short(platform, label="platform", max_len=40),
             validate_url(url), _validate_short(heat, label="heat", max_len=40),
             _validate_short(note, label="note", max_len=NOTE_MAX),
             validate_iso_date(entry_date, label="entry_date") or datetime.now(UTC).date().isoformat(),
             now, now),
        )
    with db.db_session(commit=False) as conn:
        row = conn.execute("SELECT * FROM hot_entries WHERE id = ?", (hid,)).fetchone()
    return row_to_hot_entry(row)


def hot_from_feed(*, ids: list[str]) -> dict[str, Any]:
    """feed_items 批量转素材池（SPEC-12 §2）。按 URL/标题去重防重复转入。"""
    if not ids or not all(isinstance(i, str) and i for i in ids):
        raise ValidationError("ids 必须是非空字符串数组", detail={"ids": str(ids)[:120]})
    created: list[dict[str, Any]] = []
    skipped: list[str] = []
    now = db.utcnow()
    today = datetime.now(UTC).date().isoformat()
    with db.db_session() as conn:
        for fid in ids:
            row = conn.execute("SELECT * FROM feed_items WHERE id = ?", (fid,)).fetchone()
            if row is None:
                skipped.append(fid)
                continue
            dup = conn.execute(
                "SELECT 1 FROM hot_entries WHERE source='rss' AND (url = ? OR title = ?) LIMIT 1",
                (row["url"] or "\x00", row["title"]),
            ).fetchone()
            if dup:
                skipped.append(fid)
                continue
            sub = conn.execute(
                "SELECT platform FROM subscriptions WHERE id = ?", (row["subscription_id"],)
            ).fetchone()
            hid = f"hot-{uuid.uuid4().hex[:16]}"
            conn.execute(
                "INSERT INTO hot_entries (id, title, source, platform, url, heat, note,"
                " entry_date, status, digest_id, created_at, updated_at)"
                " VALUES (?,?,'rss',?,?,'',?,?,'pending','',?,?)",
                (
                    hid,
                    row["title"],
                    (sub["platform"] if sub else "") or "",
                    row["url"] or "",
                    (row["summary"] or "")[:NOTE_MAX],
                    (row["published_at"] or today)[:10],
                    now,
                    now,
                ),
            )
            created.append({"id": hid, "title": row["title"], "feed_item_id": fid})
    return {"created": created, "skipped": skipped, "inserted": len(created)}


def update_hot_entry(entry_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """改 status / note（素材池归档、备注）。digest_id 只由 digest 流程写。"""
    with db.db_session(commit=False) as conn:
        row = conn.execute("SELECT * FROM hot_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise NotFound("热点条目不存在", detail={"entry_id": entry_id})
    sets: list[str] = []
    args: list[Any] = []
    if "status" in changes and changes["status"] is not None:
        if changes["status"] not in HOT_STATUS_VALUES:
            raise ValidationError(
                f"status 只允许 {' / '.join(HOT_STATUS_VALUES)}", detail={"status": changes["status"]}
            )
        sets.append("status = ?")
        args.append(changes["status"])
    if "note" in changes and changes["note"] is not None:
        sets.append("note = ?")
        args.append(_validate_short(changes["note"], label="note", max_len=NOTE_MAX))
    if sets:
        sets.append("updated_at = ?")
        args.append(db.utcnow())
        args.append(entry_id)
        with db.db_session() as conn:
            conn.execute(f"UPDATE hot_entries SET {', '.join(sets)} WHERE id = ?", args)
        with db.db_session(commit=False) as conn:
            row = conn.execute("SELECT * FROM hot_entries WHERE id = ?", (entry_id,)).fetchone()
    return row_to_hot_entry(row)


# ---------------------------------------------------------------------------
# 日报回读
# ---------------------------------------------------------------------------


def list_digests(*, limit: int = 30) -> dict[str, Any]:
    with db.db_session(commit=False) as conn:
        rows = conn.execute(
            "SELECT * FROM hot_digests ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    items = [row_to_digest(r) for r in rows]
    return {"items": items, "total": len(items)}


def get_digest(digest_id: str) -> dict[str, Any]:
    with db.db_session(commit=False) as conn:
        row = conn.execute("SELECT * FROM hot_digests WHERE id = ?", (digest_id,)).fetchone()
    if row is None:
        raise NotFound("日报不存在", detail={"digest_id": digest_id})
    return row_to_digest(row)


# ---------------------------------------------------------------------------
# 算法追踪（手工时间线，SPEC-12 §0 D5）
# ---------------------------------------------------------------------------


def list_algorithm_notes(*, platform: str = "") -> dict[str, Any]:
    sql = "SELECT * FROM algorithm_notes WHERE 1=1"
    args: list[Any] = []
    if platform:
        sql += " AND platform = ?"
        args.append(platform)
    sql += " ORDER BY noted_at DESC, created_at DESC"
    with db.db_session(commit=False) as conn:
        rows = conn.execute(sql, args).fetchall()
    items = [row_to_algorithm_note(r) for r in rows]
    return {"items": items, "total": len(items),
            "notice": "自动追踪依赖平台数据源（无公开接口），当前为手工登记时间线"}


def create_algorithm_note(
    *, platform: str, noted_at: str, change: str, impact: str = "", source: str = ""
) -> dict[str, Any]:
    if not isinstance(platform, str) or not platform.strip():
        raise ValidationError("platform 不能为空", hint="哪个平台的规则变化，如 xhs / dy / gzh")
    p = platform.strip()
    if len(p) > 40:
        raise ValidationError("platform 最长 40 字", detail={"max": 40})
    d = validate_iso_date(noted_at, label="noted_at", allow_empty=False)
    if not isinstance(change, str) or not change.strip():
        raise ValidationError("变化内容不能为空", hint="写清楚规则改了什么")
    c = change.strip()
    if len(c) > 500:
        raise ValidationError(f"变化内容最长 500 字（当前 {len(c)} 字）", detail={"max": 500})
    nid = f"algo-{uuid.uuid4().hex[:16]}"
    now = db.utcnow()
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO algorithm_notes (id, platform, noted_at, change, impact, source,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (nid, p, d, c, _validate_short(impact, label="impact", max_len=NOTE_MAX),
             _validate_short(source, label="source", max_len=200), now, now),
        )
    with db.db_session(commit=False) as conn:
        row = conn.execute("SELECT * FROM algorithm_notes WHERE id = ?", (nid,)).fetchone()
    return row_to_algorithm_note(row)


def delete_algorithm_note(note_id: str) -> dict[str, Any]:
    with db.db_session(commit=False) as conn:
        row = conn.execute("SELECT 1 FROM algorithm_notes WHERE id = ?", (note_id,)).fetchone()
    if row is None:
        raise NotFound("算法记录不存在", detail={"note_id": note_id})
    with db.db_session() as conn:
        conn.execute("DELETE FROM algorithm_notes WHERE id = ?", (note_id,))
    return {"ok": True, "id": note_id}
