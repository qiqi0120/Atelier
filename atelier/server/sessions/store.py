"""SPEC-03 §5 · 会话 / 消息 CRUD + 上传落盘。

只做「存」：SQLite（查询快）+ ``var/sessions/<sid>/``（每轮事件真相源）。
流式、中断、并发锁在 :mod:`.manager`。

**路径纪律（SPEC-01 §1 铁律）**：本文件不出现 ``os.path.join`` / f-string 拼路径，
全部走 :mod:`atelier.server.paths`。上传目录 ``outputs/_uploads/<sid>`` 由
:func:`upload_dir` 用 ``paths.resolve_inside`` 拼（spec 没给这个函数，且
``paths.py`` 属地基层不在本域可写范围内——见交付报告的偏差登记）。
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from .. import paths
from ..core import db, models
from ..errors import NotFound, ValidationError

__all__ = [
    "ANSWER_PREFIX",
    "DEFAULT_UPLOAD_DIR_NAME",
    "MAX_UPLOAD_BYTES",
    "QUESTION_PREFIX",
    "TITLE_MAX",
    "UPLOAD_MIME_PREFIXES",
    "UPLOAD_PROJECT",
    "UPLOAD_SUFFIXES",
    "add_message",
    "answered_questions",
    "create_session",
    "delete_session",
    "get_session",
    "group_sessions",
    "list_messages",
    "list_questions",
    "list_sessions",
    "mark_answered",
    "mark_question",
    "new_id",
    "record_artifact",
    "title_from_text",
    "update_session",
    "upload_dir",
]

#: 新会话默认标题；首条消息到达后用 :func:`title_from_text` 覆盖
DEFAULT_TITLE = "新会话"

#: SPEC-03 §5「title 取首条消息前 20 字」
TITLE_MAX = 20

#: 上传落盘根目录名（相对 ``outputs/``，即 ``outputs/_uploads/<sid>/``）
DEFAULT_UPLOAD_DIR_NAME = "_uploads"

#: SPEC-03 §4：单文件 ≤ 200MB
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

#: SPEC-03 §4 类型白名单
UPLOAD_MIME_PREFIXES: tuple[str, ...] = ("image/", "video/", "audio/")
UPLOAD_SUFFIXES: tuple[str, ...] = (".pdf", ".docx", ".md", ".txt", ".csv", ".xlsx")

#: 上传不是某个「项目」的产物，但 artifacts.project 是 NOT NULL——统一记到保留桶
UPLOAD_PROJECT = "uploads"

#: 答案留痕的 system 消息前缀。SPEC-01 §7 的 messages 表没有「已答问题」列，
#: 而 schema 是冻结的，所以答案用一条隐藏的 system 消息落库，重启后仍能恢复
#: ``answered_questions``（F-B7 的真正落点）。该消息不进 UI 消息流。
ANSWER_PREFIX = "atelier:answered-question:"

#: 问题留痕前缀（同样不进 UI 消息流）
QUESTION_PREFIX = "atelier:question:"


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def new_id(prefix: str) -> str:
    """生成内部 id（``s_``/``m_``/``t_``/``a_`` 前缀 + 16 位 hex）。

    满足 ``paths.validate_id`` 的白名单（字母数字 - _）。
    """
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def title_from_text(text: str) -> str:
    """首条消息前 20 字当标题；空白折叠、去首尾空白。"""
    flat = " ".join((text or "").split())
    return flat[:TITLE_MAX] or DEFAULT_TITLE


def upload_dir(session_id: str) -> Path:
    """``outputs/_uploads/<session_id>/``（幂等创建）。"""
    paths.validate_id(session_id, "session_id")
    target = paths.resolve_inside(paths.OUTPUTS, f"{DEFAULT_UPLOAD_DIR_NAME}/{session_id}")
    target.mkdir(parents=True, exist_ok=True)
    return target


def check_upload_type(name: str, mime: str) -> str | None:
    """返回后缀（含 ``.``，小写）；不合规返回 ``None``。

    白名单见 :data:`UPLOAD_MIME_PREFIXES` / :data:`UPLOAD_SUFFIXES`。
    """
    suffix = Path(name or "x").suffix.lower() or ".bin"
    m = (mime or "").lower()
    if m.startswith(UPLOAD_MIME_PREFIXES):
        return suffix
    if suffix in UPLOAD_SUFFIXES:
        return suffix
    return None


def kind_for(mime: str, suffix: str) -> Literal["image", "video", "audio", "doc"]:
    m = (mime or "").lower()
    if m.startswith("image/") or suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic"):
        return "image"
    if m.startswith("video/") or suffix in (".mp4", ".mov", ".mkv", ".webm"):
        return "video"
    if m.startswith("audio/") or suffix in (".mp3", ".wav", ".m4a", ".aac"):
        return "audio"
    return "doc"


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------


def _row_to_session(row: Any) -> models.Session:
    return models.Session(
        id=row["id"],
        title=row["title"] or DEFAULT_TITLE,
        profile_id=row["profile_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        archived=bool(row["archived"]),
        last_turn_id=row["last_turn_id"],
    )


def create_session(
    *, title: str | None = None, profile_id: str | None = None
) -> models.Session:
    """新建会话。``title`` 省略时留 :data:`DEFAULT_TITLE`，首条消息到达后再改。"""
    sid = new_id("s")
    now = db.utcnow()
    name = (title or "").strip()[:TITLE_MAX] or DEFAULT_TITLE
    with db.db_session() as c:
        c.execute(
            "INSERT INTO sessions(id,title,profile_id,archived,last_turn_id,created_at,updated_at)"
            " VALUES(?,?,?,0,NULL,?,?)",
            (sid, name, profile_id, now, now),
        )
    return models.Session(
        id=sid,
        title=name,
        profile_id=profile_id,
        created_at=datetime.fromisoformat(now),
        updated_at=datetime.fromisoformat(now),
        archived=False,
        last_turn_id=None,
    )


def get_session(session_id: str, *, required: bool = True) -> models.Session | None:
    row = db.get_conn().execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        if not required:
            return None
        raise NotFound(
            "会话不存在或已删除",
            detail={"session_id": session_id},
            hint="回到会话列表重新选一个，或点「＋ 新会话」",
        )
    return _row_to_session(row)


def list_sessions(*, include_archived: bool = True) -> list[models.Session]:
    """按 ``updated_at`` 倒序（SPEC-03 §5）。"""
    sql = "SELECT * FROM sessions"
    if not include_archived:
        sql += " WHERE archived=0"
    sql += " ORDER BY updated_at DESC, rowid DESC"
    return [_row_to_session(r) for r in db.get_conn().execute(sql).fetchall()]


def update_session(
    session_id: str,
    *,
    title: str | None = None,
    archived: bool | None = None,
    profile_id: str | None = None,
    last_turn_id: str | None = None,
    touch: bool = True,
) -> models.Session:
    """重命名 / 归档 / 换画像 / 记 last_turn_id。未传的字段不动。"""
    get_session(session_id)  # 不存在 → NotFound
    sets: list[str] = []
    args: list[Any] = []
    if title is not None:
        clean = " ".join(title.split())[:TITLE_MAX]
        if not clean:
            raise ValidationError("标题不能为空", detail={"title": title}, hint="给会话起个名字，或取消重命名")
        sets.append("title=?")
        args.append(clean)
    if archived is not None:
        sets.append("archived=?")
        args.append(1 if archived else 0)
    if profile_id is not None:
        sets.append("profile_id=?")
        args.append(profile_id)
    if last_turn_id is not None:
        sets.append("last_turn_id=?")
        args.append(last_turn_id)
    if touch:
        sets.append("updated_at=?")
        args.append(db.utcnow())
    if sets:
        args.append(session_id)
        with db.db_session() as c:
            c.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id=?", args)
    return get_session(session_id)  # type: ignore[return-value]


def delete_session(session_id: str) -> dict[str, Any]:
    """删会话 + 它的消息 + ``var/sessions/<sid>/`` 落盘。

    外键 ``ON DELETE CASCADE`` 负责 messages；落盘目录删前过 ``is_system_path``。
    """
    get_session(session_id)
    with db.db_session() as c:
        c.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        c.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    removed_dir = False
    d = paths.session_dir(session_id)
    if d.exists() and not paths.is_system_path(d):
        shutil.rmtree(d, ignore_errors=True)
        removed_dir = True
    return {"id": session_id, "removed": True, "removed_turn_logs": removed_dir}


def group_sessions(sessions: Sequence[models.Session]) -> list[dict[str, Any]]:
    """按 SPEC-03 §5 分组：今天 / 昨天 / 更早 / 已归档。

    归档会话单独成组（无论日期）；未归档按**本地**日期判定今天/昨天。
    """
    today = datetime.now().astimezone().date()
    yesterday = today - timedelta(days=1)
    groups: dict[str, dict[str, Any]] = {
        "today": {"key": "today", "label": "今天", "items": []},
        "yesterday": {"key": "yesterday", "label": "昨天", "items": []},
        "earlier": {"key": "earlier", "label": "更早", "items": []},
        "archived": {"key": "archived", "label": "已归档", "items": []},
    }
    for s in sessions:
        if s.archived:
            groups["archived"]["items"].append(s)
            continue
        day = s.updated_at.astimezone().date()
        if day == today:
            groups["today"]["items"].append(s)
        elif day == yesterday:
            groups["yesterday"]["items"].append(s)
        else:
            groups["earlier"]["items"].append(s)
    return [g for g in groups.values() if g["items"]]


# ---------------------------------------------------------------------------
# 消息
# ---------------------------------------------------------------------------


def _row_to_message(row: Any) -> models.Message:
    return models.Message(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        text=row["text"] or "",
        turn_id=row["turn_id"],
        attachments=[models.Attachment.model_validate(a) for a in (db.loads(row["attachments"], []) or [])],
        gate_report=db.loads(row["gate_report"], None),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def add_message(
    session_id: str,
    role: Literal["user", "assistant", "system"],
    text: str,
    *,
    turn_id: str | None = None,
    attachments: Iterable[models.Attachment] | None = None,
    gate_report: dict[str, Any] | None = None,
) -> models.Message:
    """写一条消息并把会话 ``updated_at`` 顶上去。"""
    get_session(session_id)  # 不存在 → NotFound（避免孤儿消息）
    mid = new_id("m")
    now = db.utcnow()
    atts = [a.model_dump(mode="json") for a in (attachments or [])]
    with db.db_session() as c:
        c.execute(
            "INSERT INTO messages(id,session_id,role,text,turn_id,attachments,gate_report,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (
                mid,
                session_id,
                role,
                text or "",
                turn_id,
                json.dumps(atts, ensure_ascii=False) if atts else None,
                json.dumps(gate_report, ensure_ascii=False) if gate_report else None,
                now,
            ),
        )
        c.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
    return models.Message(
        id=mid,
        session_id=session_id,
        role=role,
        text=text or "",
        turn_id=turn_id,
        attachments=list(attachments or []),
        gate_report=gate_report,
        created_at=datetime.fromisoformat(now),
    )


def list_messages(
    session_id: str, *, limit: int = 50, offset: int = 0, include_system: bool = False
) -> list[models.Message]:
    """按时间**倒序**分页取（SPEC-03 §5），再翻回展示顺序。

    ``created_at`` 精确到秒，同秒内用 ``rowid`` 兜底排序，否则一轮里的
    user/assistant 两条会顺序颠倒。
    """
    get_session(session_id)  # 不存在 → NotFound
    where = "session_id=?"
    args: list[Any] = [session_id]
    if not include_system:
        # 问题/答案的留痕消息不进 UI 消息流（各自有单独接口给）
        where += " AND NOT (role='system' AND text LIKE 'atelier:%')"
    rows = db.get_conn().execute(
        f"SELECT * FROM messages WHERE {where} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
        (*args, max(1, min(limit, 500)), max(0, offset)),
    ).fetchall()
    return [_row_to_message(r) for r in reversed(rows)]


def message_count(session_id: str, *, include_system: bool = False) -> int:
    where = "session_id=?"
    args: list[Any] = [session_id]
    if not include_system:
        where += " AND NOT (role='system' AND text LIKE 'atelier:%')"
    return int(db.get_conn().execute(f"SELECT COUNT(*) FROM messages WHERE {where}", args).fetchone()[0])


# ---------------------------------------------------------------------------
# 问答题（F-B7）：问题与答案都留痕在隐藏 system 消息里
# ---------------------------------------------------------------------------


def mark_question(session_id: str, question_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """落盘一个 agent 反问（SPEC-03 §3.1「服务端在 messages 表存 question」）。"""
    paths.validate_id(session_id, "session_id")
    payload = {
        "question_id": question_id,
        "text": str(data.get("text") or ""),
        "options": list(data.get("options") or []),
        "multiple": bool(data.get("multiple")),
    }
    add_message(
        session_id,
        "system",
        QUESTION_PREFIX + json.dumps(payload, ensure_ascii=False),
    )
    return payload


def list_questions(session_id: str) -> list[dict[str, Any]]:
    """按提问顺序返回问题，并挂上答案（刷新页面后问答题卡片仍是「已确认」态）。"""
    paths.validate_id(session_id, "session_id")
    rows = db.get_conn().execute(
        "SELECT text FROM messages WHERE session_id=? AND role='system'"
        " AND (text LIKE ? OR text LIKE ?) ORDER BY rowid",
        (session_id, f"{QUESTION_PREFIX}%", f"{ANSWER_PREFIX}%"),
    ).fetchall()
    questions: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for r in rows:
        raw = r["text"] or ""
        try:
            body = json.loads(raw.split(":", 2)[2])
        except (json.JSONDecodeError, IndexError):
            continue
        if raw.startswith(QUESTION_PREFIX):
            qid = str(body.get("question_id") or "")
            if not qid or qid in questions:
                continue
            questions[qid] = {**body, "turn_id": None, "answered": None}
            order.append(qid)
        else:
            qid = str(body.get("question_id") or "")
            if qid in questions:
                questions[qid]["answered"] = {
                    "option_key": body.get("option_key"),
                    "label": body.get("label"),
                }
    return [questions[q] for q in order]


def mark_answered(session_id: str, question_id: str, option_key: str, label: str) -> dict[str, str]:
    """记一条答案（隐藏 system 消息）+ 落盘，重启后仍能过滤重复提问。"""
    paths.validate_id(session_id, "session_id")
    payload = {
        "question_id": question_id,
        "option_key": option_key,
        "label": label,
    }
    add_message(
        session_id,
        "system",
        ANSWER_PREFIX + json.dumps(payload, ensure_ascii=False),
        attachments=None,
    )
    return payload


def answered_questions(session_id: str) -> set[str]:
    """从落库的答案留痕重建已答问题集合（F-B7 会话级去重的真相源）。"""
    paths.validate_id(session_id, "session_id")
    rows = db.get_conn().execute(
        "SELECT text FROM messages WHERE session_id=? AND role='system' AND text LIKE ?",
        (session_id, f"{ANSWER_PREFIX}%"),
    ).fetchall()
    out: set[str] = set()
    for r in rows:
        try:
            qid = json.loads((r["text"] or "")[len(ANSWER_PREFIX) :]).get("question_id")
        except (json.JSONDecodeError, AttributeError):
            continue
        if qid:
            out.add(str(qid))
    return out


# ---------------------------------------------------------------------------
# 产物索引
# ---------------------------------------------------------------------------


def record_artifact(
    *,
    session_id: str,
    turn_id: str | None,
    rel_path: str,
    kind: str,
    size: int,
    mime: str,
    project: str,
    zone: str,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    """写 artifacts 索引（只存元数据，文件本身在文件系统上）。"""
    aid = artifact_id or new_id("a")
    now = db.utcnow()
    with db.db_session() as c:
        c.execute(
            "INSERT OR REPLACE INTO artifacts"
            "(id,project,zone,rel_path,kind,size,mime,session_id,turn_id,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (aid, project, zone, rel_path, kind, int(size), mime, session_id, turn_id, now),
        )
    return {
        "id": aid,
        "project": project,
        "zone": zone,
        "path": rel_path,
        "kind": kind,
        "size": int(size),
        "mime": mime,
        "session_id": session_id,
        "turn_id": turn_id,
        "created_at": now,
    }

