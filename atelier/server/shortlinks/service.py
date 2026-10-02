"""M4 · 短链服务（SPEC-14 §0 D4 / F-G21）。

本地短链：8 位 [a-z0-9] 随机码 → 302 跳转 + hits 计数（本地追踪闭环，
无公网域，如实标注）。生码与查询走 ``/api/shortlinks``；跳转路由挂根路径
``/s/{code}``（在 main.py）。
"""

from __future__ import annotations

import secrets
import sqlite3
from typing import Any

from atelier.server.core import db
from atelier.server.errors import NotFound, ValidationError

__all__ = ["CODE_LEN", "create_shortlink", "get_shortlink", "hit", "list_shortlinks"]

CODE_LEN = 8
CODE_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def row_to_shortlink(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "code": row["code"],
        "target": row["target"],
        "note": row["note"] or "",
        "hits": row["hits"],
        "created_at": row["created_at"],
    }


def create_shortlink(*, target: str, note: str = "") -> dict[str, Any]:
    t = (target or "").strip()
    if not t.startswith(("http://", "https://")):
        raise ValidationError(
            "target 必须以 http:// 或 https:// 开头",
            detail={"target": t[:120]},
        )
    if len(t) > 2000:
        raise ValidationError("target 过长（>2000 字符）", detail={"max": 2000})
    note_v = (note or "").strip()[:200]
    with db.db_session(commit=False) as conn:
        dup = conn.execute("SELECT * FROM shortlinks WHERE target = ? LIMIT 1", (t,)).fetchone()
    if dup is not None:
        return row_to_shortlink(dup)  # 同目标复用同码（幂等）
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
    with db.db_session() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO shortlinks (code, target, note, hits, created_at) VALUES (?,?,?,0,?)",
            (code, t, note_v, db.utcnow()),
        )
    return get_shortlink(code)


def get_shortlink(code: str) -> dict[str, Any]:
    with db.db_session(commit=False) as conn:
        row = conn.execute("SELECT * FROM shortlinks WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise NotFound("短链不存在或已失效", detail={"code": code})
    return row_to_shortlink(row)


def hit(code: str) -> str | None:
    """计数并返回目标（不存在返回 None；跳转由路由做 302）。"""
    with db.db_session() as conn:
        row = conn.execute("SELECT target FROM shortlinks WHERE code = ?", (code,)).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE shortlinks SET hits = hits + 1 WHERE code = ?", (code,))
        return str(row["target"])


def list_shortlinks() -> dict[str, Any]:
    with db.db_session(commit=False) as conn:
        rows = conn.execute("SELECT * FROM shortlinks ORDER BY created_at DESC LIMIT 200").fetchall()
    items = [row_to_shortlink(r) for r in rows]
    return {"items": items, "total": len(items), "notice": "短链是本地服务（/s/<code>），追踪为本地计数"}
