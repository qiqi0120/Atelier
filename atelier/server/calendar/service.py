"""SPEC-09 · 日历域服务层：事件 CRUD + 提醒窗口 + 内置节点补种。

职责边界：

- ``calendar_events`` 是**全局表**，不带 ``profile_id``（SPEC-09 §0 D2）：
  节日/平台活动不属于某个画像；建议出的选题才绑画像。
- 「提前 N 天提醒」是**查询式**（D5）：:func:`upcoming` 按每条事件自带的
  ``remind_days`` 算激活窗口，不做后台推送/定时器。
- 日期一律 ``YYYY-MM-DD`` 零填充 ISO 文本、本地时区；服务函数带 ``today``
  形参（默认 ``date.today()``）保证可测（D7）。
- 内置节点只含公历确定日 + 可计算的母亲节/父亲节（D4）；农历不内置，
  不引农历依赖，用户手工添加。
"""

from __future__ import annotations

import calendar as _cal
import re
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from atelier.server.core import db
from atelier.server.errors import NotFound, ValidationError
from atelier.server.topics import service as topic_service

__all__ = [
    "DEFAULT_REMIND",
    "KIND_VALUES",
    "NOTE_MAX",
    "REMIND_RANGE",
    "TITLE_MAX",
    "create_event",
    "delete_event",
    "events_between",
    "get_event",
    "list_month",
    "local_today",
    "row_to_event",
    "seed",
    "upcoming",
    "update_event",
]

#: 事件标题/备注上限（与选题同口径，SPEC-09 §5）
TITLE_MAX = 80
NOTE_MAX = 200
#: kind 枚举（SPEC-09 §1）：节日 / 电商节点 / 行业事件 / 平台活动
KIND_VALUES: tuple[str, ...] = ("festival", "ecommerce", "industry", "platform")
#: 提前提醒天数范围与默认值（SPEC-09 §0 D5）
REMIND_RANGE = (0, 30)
DEFAULT_REMIND = 3

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")

#: 日历语义的「今天」固定走北京时间：节假日/电商大促的日期本来就以中国日历为准，
#: 显式时区同时消除机器时区差异（SPEC-09 §0 D7 的落地口径）。
_TZ = ZoneInfo("Asia/Shanghai")


def local_today() -> date:
    """当前北京时间的日期。全域的 ``today`` 缺省值只有这一个出口。"""
    return datetime.now(_TZ).date()


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


def validate_title(title: Any) -> str:
    """strip 后 1..80 字；非法抛 ``ValidationError``（SPEC-09 §5）。"""
    if not isinstance(title, str) or not title.strip():
        raise ValidationError("事件标题不能为空", hint="给节点起个能一眼看懂的名字")
    t = title.strip()
    if len(t) > TITLE_MAX:
        raise ValidationError(
            f"事件标题最长 {TITLE_MAX} 字（当前 {len(t)} 字）",
            detail={"title": t, "max": TITLE_MAX},
            hint="缩短标题；细节写进备注",
        )
    return t


def _validate_note(note: Any) -> str:
    if note is None:
        return ""
    if not isinstance(note, str):
        raise ValidationError("备注必须是字符串", detail={"note": note})
    n = note.strip()
    if len(n) > NOTE_MAX:
        raise ValidationError(f"备注最长 {NOTE_MAX} 字（当前 {len(n)} 字）", detail={"max": NOTE_MAX})
    return n


def _to_date(value: Any, label: str) -> date:
    """严格 ``YYYY-MM-DD``：可解析且零填充，否则 ``ValidationError``。"""
    if not isinstance(value, str):
        raise ValidationError(f"{label} 必须是 YYYY-MM-DD 格式的字符串", detail={label: value})
    v = value.strip()
    try:
        d = date.fromisoformat(v)
    except ValueError as exc:
        raise ValidationError(
            f"{label} 不是合法日期", detail={label: value}, hint="格式：YYYY-MM-DD"
        ) from exc
    if d.isoformat() != v:
        raise ValidationError(f"{label} 必须是零填充的 YYYY-MM-DD", detail={label: value})
    return d


def _validate_kind(kind: Any) -> str:
    if kind not in KIND_VALUES:
        raise ValidationError(
            f"kind 只允许 {' / '.join(KIND_VALUES)}",
            detail={"kind": kind},
            hint="节日=festival，电商节点=ecommerce，行业事件=industry，平台活动=platform",
        )
    return kind


def _validate_remind(days: Any) -> int:
    if isinstance(days, bool) or not isinstance(days, int) \
            or not REMIND_RANGE[0] <= days <= REMIND_RANGE[1]:
        raise ValidationError(
            f"remind_days 必须是 {REMIND_RANGE[0]}..{REMIND_RANGE[1]} 的整数",
            detail={"remind_days": days},
        )
    return days


# ---------------------------------------------------------------------------
# 事件 CRUD
# ---------------------------------------------------------------------------


def row_to_event(row: sqlite3.Row) -> dict[str, Any]:
    """行 → API 形状。全包唯一的 calendar_events 行转换出口。"""
    return {
        "id": row["id"],
        "title": row["title"],
        "date": row["date"],
        "end_date": row["end_date"] or "",
        "kind": row["kind"],
        "note": row["note"] or "",
        "remind_days": row["remind_days"],
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_event(event_id: str) -> dict[str, Any]:
    with db.db_session(commit=False) as conn:
        row = conn.execute("SELECT * FROM calendar_events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise NotFound("日历事件不存在", detail={"event_id": event_id}, hint="可能已被删除，刷新看看")
    return row_to_event(row)


def create_event(
    *,
    title: str,
    date: str,
    end_date: str | None = None,
    kind: str,
    note: str | None = None,
    remind_days: int = DEFAULT_REMIND,
) -> dict[str, Any]:
    """新建事件，``source=manual``。内置节点补种不走这里（见 :func:`seed`）。"""
    t = validate_title(title)
    d = _to_date(date, "date")
    e = "" if not end_date else _to_date(end_date, "end_date").isoformat()
    if e and e < d.isoformat():
        raise ValidationError(
            "end_date 不能早于 date", detail={"date": d.isoformat(), "end_date": e}
        )
    k = _validate_kind(kind)
    n = _validate_note(note)
    r = _validate_remind(remind_days)
    eid = f"event-{uuid.uuid4().hex[:16]}"
    now = db.utcnow()
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO calendar_events (id, title, date, end_date, kind, note,"
            " remind_days, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (eid, t, d.isoformat(), e, k, n, r, "manual", now, now),
        )
    return get_event(eid)


def update_event(event_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """改 title / date / end_date / kind / note / remind_days。全空的 PATCH 原样返回。"""
    current = get_event(event_id)
    sets: list[str] = []
    args: list[Any] = []
    if "title" in changes and changes["title"] is not None:
        sets.append("title = ?")
        args.append(validate_title(changes["title"]))
    if "kind" in changes and changes["kind"] is not None:
        sets.append("kind = ?")
        args.append(_validate_kind(changes["kind"]))
    if "note" in changes and changes["note"] is not None:
        sets.append("note = ?")
        args.append(_validate_note(changes["note"]))
    if "remind_days" in changes and changes["remind_days"] is not None:
        sets.append("remind_days = ?")
        args.append(_validate_remind(changes["remind_days"]))

    # 日期组合校验：以「改动后的意图」为准，逐项取新值、缺省回落当前值
    new_date = _to_date(changes["date"], "date") if changes.get("date") is not None \
        else date.fromisoformat(current["date"])
    new_end_raw = changes.get("end_date")
    if new_end_raw is not None:
        new_end = "" if new_end_raw == "" else _to_date(new_end_raw, "end_date").isoformat()
    else:
        new_end = current["end_date"]
    if new_end and new_end < new_date.isoformat():
        raise ValidationError(
            "end_date 不能早于 date",
            detail={"date": new_date.isoformat(), "end_date": new_end},
        )
    if changes.get("date") is not None:
        sets.append("date = ?")
        args.append(new_date.isoformat())
    if changes.get("end_date") is not None:
        sets.append("end_date = ?")
        args.append(new_end)

    if sets:
        sets.append("updated_at = ?")
        args.append(db.utcnow())
        args.append(event_id)
        with db.db_session() as conn:
            conn.execute(f"UPDATE calendar_events SET {', '.join(sets)} WHERE id = ?", args)
    return current if not sets else get_event(event_id)


def delete_event(event_id: str) -> dict[str, Any]:
    get_event(event_id)  # 不存在 → 404
    with db.db_session() as conn:
        conn.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
    return {"ok": True, "id": event_id}


# ---------------------------------------------------------------------------
# 查询：月视图 / 提醒窗口
# ---------------------------------------------------------------------------


def events_between(start: str, end: str) -> list[dict[str, Any]]:
    """与 ``[start, end]`` 有重叠的事件（含跨期多日活动），date 升序。

    ``end_date`` 落库用空串表示「无」（与库内其他文本列一致），所以这里用
    ``NULLIF(end_date, '')`` 归空后再 COALESCE——单日事件以自身 date 参与
    重叠判定。
    """
    with db.db_session(commit=False) as conn:
        rows = conn.execute(
            "SELECT * FROM calendar_events WHERE date <= ?"
            " AND COALESCE(NULLIF(end_date, ''), date) >= ?"
            " ORDER BY date, title",
            (end, start),
        ).fetchall()
    return [row_to_event(r) for r in rows]


def list_month(month: str = "", today: date | None = None) -> dict[str, Any]:
    """月视图数据：``{month, events, topics}``。

    events 按「与当月有重叠」判定；topics 是 ``due_date`` 落在当月的选题
    （全状态，SPEC-09 §6：日历区分内容条目与平台活动两类）。
    """
    today = today or local_today()
    m = _MONTH_RE.match(month.strip()) if month else None
    if month and not m:
        raise ValidationError("month 必须是 YYYY-MM 格式", detail={"month": month})
    y, mo = (int(m.group(1)), int(m.group(2))) if m else (today.year, today.month)
    last_day = _cal.monthrange(y, mo)[1]
    start = date(y, mo, 1).isoformat()
    end = date(y, mo, last_day).isoformat()
    with db.db_session(commit=False) as conn:
        rows = conn.execute(
            "SELECT * FROM topics WHERE due_date IS NOT NULL AND due_date != ''"
            " AND due_date BETWEEN ? AND ? ORDER BY due_date, created_at",
            (start, end),
        ).fetchall()
    return {
        "month": f"{y:04d}-{mo:02d}",
        "events": events_between(start, end),
        "topics": [topic_service.row_to_topic(r) for r in rows],
    }


def upcoming(*, days: int = 14, today: date | None = None) -> dict[str, Any]:
    """未来 ``days`` 天（含今天）的节点 + 提醒状态（SPEC-09 §3，规则代码持有）。"""
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 31:
        raise ValidationError("days 必须是 1..31 的整数", detail={"days": days})
    today = today or local_today()
    window_end = (today + timedelta(days=days - 1)).isoformat()
    items: list[dict[str, Any]] = []
    for ev in events_between(today.isoformat(), window_end):
        d = date.fromisoformat(ev["date"])
        end_d = date.fromisoformat(ev["end_date"] or ev["date"])
        remind_start = d - timedelta(days=ev["remind_days"])
        items.append({
            **ev,
            "remind_active": remind_start <= today <= end_d,
            "days_left": (d - today).days,  # >0 还有 N 天；0 今天；<0 多日活动进行中
        })
    return {"today": today.isoformat(), "items": items}


# ---------------------------------------------------------------------------
# 内置节点补种（SPEC-09 §0 D4）
# ---------------------------------------------------------------------------

#: 公历固定节点（月, 日）。农历节日（春节/中秋/端午/清明/七夕/年货节）不内置，
#: 用户手工添加——不引农历依赖。
_FIXED_NODES: tuple[tuple[str, str, int, int], ...] = (
    ("元旦", "festival", 1, 1),
    ("情人节", "festival", 2, 14),
    ("38 女神节", "ecommerce", 3, 8),
    ("劳动节", "festival", 5, 1),
    ("520", "festival", 5, 20),
    ("儿童节", "festival", 6, 1),
    ("618 大促", "ecommerce", 6, 18),
    ("99 划算节", "ecommerce", 9, 9),
    ("国庆节", "festival", 10, 1),
    ("万圣夜", "festival", 10, 31),
    ("双11", "ecommerce", 11, 11),
    ("双12", "ecommerce", 12, 12),
    ("圣诞节", "festival", 12, 25),
)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """某月第 ``n`` 个 ``weekday``（0=周一 … 6=周日）的日期。"""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _builtin_dates(year: int) -> list[tuple[str, str, date]]:
    out = [(t, k, date(year, m, d)) for t, k, m, d in _FIXED_NODES]
    out.append(("母亲节", "festival", _nth_weekday(year, 5, 6, 2)))
    out.append(("父亲节", "festival", _nth_weekday(year, 6, 6, 3)))
    return out


def seed(*, year: int | None = None, today: date | None = None) -> dict[str, Any]:
    """补种内置节点：只补 ``(title, date)`` 不存在的，幂等（SPEC-09 §5）。

    删除内置条目后重新导入会带回——语义就是「重新导入」（D4）。
    """
    today = today or local_today()
    if year is None:
        year = today.year
    if isinstance(year, bool) or not isinstance(year, int) or not 2000 <= year <= 2100:
        raise ValidationError("year 必须是 2000..2100 的整数", detail={"year": year})
    added = skipped = 0
    now = db.utcnow()
    with db.db_session() as conn:
        for title, kind, d in _builtin_dates(year):
            exists = conn.execute(
                "SELECT 1 FROM calendar_events WHERE title = ? AND date = ?",
                (title, d.isoformat()),
            ).fetchone()
            if exists:
                skipped += 1
                continue
            conn.execute(
                "INSERT INTO calendar_events (id, title, date, end_date, kind, note,"
                " remind_days, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"event-{uuid.uuid4().hex[:16]}", title, d.isoformat(), "", kind,
                 "", DEFAULT_REMIND, "builtin", now, now),
            )
            added += 1
    return {"year": year, "added": added, "skipped": skipped}
