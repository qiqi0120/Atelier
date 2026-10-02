"""SPEC-08 · 选题域服务层：选题池 CRUD + 三个 AI 任务共用的调用/门禁路径。

职责边界：

- **池本体**（topics 表）在这里读写；评分历史（topic_scores）的写入在
  :mod:`score`，但查询入口（最新一条）由 :func:`topic_with_score` 统一给。
- **AI 调用只认 Harness 抽象**（SPEC-00 §1 ②）：流式收集 ``TEXT_DELTA``，
  SDK 类型不许出现在本包。画像经 ``TurnRequest.profile`` 内联（SPEC-02 §4），
  本域不手工拼画像文本。
- **产出先过门禁**（PLAN-M2 §3）：AI 文本落库前跑
  ``compliance + secret_scan + ai_flavor``，命中 BLOCK 抛 ``GateBlocked``——
  拒绝整批、不静默过滤，用户按改法重试。
- 本域**不落产物文件**：拆解 markdown 与结构化字段都进 SQLite
  （选题是待办性质的元数据，不是成品，PRD 原则一不适用）。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from atelier.server.core import db
from atelier.server.errors import (
    AtelierError,
    GateBlocked,
    HarnessError,
    NotFound,
    ValidationError,
)
from atelier.server.gates.base import GateInput
from atelier.server.gates.registry import run_gates
from atelier.server.harness.base import EventType, TurnRequest
from atelier.server.harness.registry import get_harness
from atelier.server.profile import store as profile_store

__all__ = [
    "AI_GATES",
    "SOURCE_VALUES",
    "STATUS_VALUES",
    "TITLE_MAX",
    "AIOutputInvalid",
    "DecodeIncomplete",
    "create_topic",
    "delete_topic",
    "extract_json",
    "get_topic",
    "latest_score",
    "list_topics",
    "row_to_topic",
    "run_ai_text",
    "topic_with_score",
    "update_topic",
    "validate_title",
]

#: SPEC-08 §0 D5 冻结的枚举。hot / calendar 留给 M2-2 / M2-3，本批写库即拒。
STATUS_VALUES: tuple[str, ...] = ("todo", "doing", "done")
SOURCE_VALUES: tuple[str, ...] = ("manual", "decode", "matrix")

#: AI 产出统一跑的门禁（SPEC-08 §4）。wordcount 不在列：选题不是发布内容，
#: 钩子的字数判定走 :mod:`hooks` 里的平台口径原语。
AI_GATES: tuple[str, ...] = ("compliance", "secret_scan", "ai_flavor")

#: 标题长度上限（SPEC-08 §1）
TITLE_MAX = 80
ANGLE_MAX = 200

_TASK_SUFFIX = (
    "【任务说明】本次是工作台选题域的结构化任务调用：只输出任务要求的 Markdown 或 JSON，"
    "不要调用工具、不要写文件、不要反问。"
)


class DecodeIncomplete(AtelierError):
    """拆解结果缺段（SPEC-08 §2）。缺段如实报错，不许硬编补齐。"""

    code = "DecodeIncomplete"
    http = 422
    default_message = "拆解结果不完整：缺少规定的段落"
    default_hint = "重试一次；连续失败就把原文贴得更完整些"


class AIOutputInvalid(AtelierError):
    """模型没按 JSON 约定输出（SPEC-08 §2）。解析失败就报错，不编造数据。"""

    code = "AIOutputInvalid"
    http = 502
    default_message = "AI 返回了约定之外的内容"
    default_hint = "重试一次；连续失败说明模型不服从输出约定，可换模型或缩小任务"


# ---------------------------------------------------------------------------
# 选题池 CRUD
# ---------------------------------------------------------------------------


def _now_pair() -> tuple[str, str]:
    now = db.utcnow()
    return now, now


def validate_title(title: Any) -> str:
    """strip 后 1..80 字；非法抛 ``ValidationError``（SPEC-08 §1）。"""
    if not isinstance(title, str) or not title.strip():
        raise ValidationError("选题标题不能为空", hint="给选题起个能一眼看懂的名字")
    t = title.strip()
    if len(t) > TITLE_MAX:
        raise ValidationError(
            f"选题标题最长 {TITLE_MAX} 字（当前 {len(t)} 字）",
            detail={"title": t, "max": TITLE_MAX},
            hint="缩短标题；细节放进「备注角度」",
        )
    return t


def _validate_angle(angle: Any) -> str:
    if angle is None:
        return ""
    if not isinstance(angle, str):
        raise ValidationError("备注角度必须是字符串", detail={"angle": angle})
    a = angle.strip()
    if len(a) > ANGLE_MAX:
        raise ValidationError(
            f"备注角度最长 {ANGLE_MAX} 字（当前 {len(a)} 字）", detail={"max": ANGLE_MAX}
        )
    return a


def row_to_topic(row: sqlite3.Row) -> dict[str, Any]:
    """行 → API 形状。全包唯一的 topics 行转换出口（matrix 回读也走这里）。"""
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "title": row["title"],
        "angle": row["angle"] or "",
        "source": row["source"],
        "source_ref": row["source_ref"] or "",
        "status": row["status"],
        "decode": row["decode"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_topics(
    *, profile_id: str | None = None, status: str = "", q: str = ""
) -> dict[str, Any]:
    """池列表，``updated_at`` 倒序。status/q 缺省不过滤。"""
    if status and status not in STATUS_VALUES:
        raise ValidationError(
            f"status 只允许 {' / '.join(STATUS_VALUES)}",
            detail={"status": status},
            hint="待做=todo，进行中=doing，已完成=done",
        )
    sql = "SELECT * FROM topics WHERE 1=1"
    args: list[Any] = []
    if profile_id:
        sql += " AND profile_id = ?"
        args.append(profile_id)
    if status:
        sql += " AND status = ?"
        args.append(status)
    if q:
        sql += " AND (title LIKE ? OR angle LIKE ?)"
        args.extend((f"%{q}%", f"%{q}%"))
    sql += " ORDER BY updated_at DESC, created_at DESC"
    with db.db_session(commit=False) as conn:
        rows = conn.execute(sql, args).fetchall()
    items = [row_to_topic(r) for r in rows]
    return {"items": items, "total": len(items)}


def create_topic(
    *,
    title: str,
    angle: str | None = None,
    profile_id: str | None = None,
    source: str = "manual",
    source_ref: str | None = None,
    decode: str | None = None,
) -> dict[str, Any]:
    """新建选题。``decode`` 字段仅 ``source=decode`` 时接受（SPEC-08 §5）。"""
    if source not in SOURCE_VALUES:
        raise ValidationError(
            f"source 只允许 {' / '.join(SOURCE_VALUES)}",
            detail={"source": source},
            hint="hot / calendar 来源留给后续批次，当前不接受",
        )
    t = validate_title(title)
    a = _validate_angle(angle)
    if decode and source != "decode":
        raise ValidationError(
            "只有来源为拆解（source=decode）的选题可以带拆解正文",
            detail={"source": source},
            hint="先调 POST /topics/decode 生成拆解，再以 source=decode 保存",
        )
    if profile_id:
        profile_store.get_profile(profile_id)  # 不存在 → ProfileNotFound(404)
    tid = f"topic-{uuid.uuid4().hex[:16]}"
    created, _ = _now_pair()
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO topics (id, profile_id, title, angle, source, source_ref, status,"
            " decode, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (tid, profile_id, t, a, source, (source_ref or "").strip(), "todo",
             decode, created, created),
        )
    return get_topic(tid)


def get_topic(topic_id: str) -> dict[str, Any]:
    with db.db_session(commit=False) as conn:
        row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if row is None:
        raise NotFound("选题不存在", detail={"topic_id": topic_id}, hint="可能已被删除，刷新列表看看")
    return row_to_topic(row)


def topic_with_score(topic_id: str) -> dict[str, Any]:
    """``{topic, score}``：score 是最新一条评分，没有则为 null（SPEC-08 §5）。"""
    topic = get_topic(topic_id)
    with db.db_session(commit=False) as conn:
        row = conn.execute(
            "SELECT * FROM topic_scores WHERE topic_id = ?"
            " ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (topic_id,),
        ).fetchone()
    score = None
    if row is not None:
        score = {
            "id": row["id"],
            "topic_id": row["topic_id"],
            "dims": db.loads(row["dims"], {}),
            "total": row["total"],
            "verdict": row["verdict"],
            "reason": row["reason"] or "",
            "created_at": row["created_at"],
        }
    return {"topic": topic, "score": score}


def update_topic(topic_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """改 title / angle / status。全空的 PATCH 原样返回（幂等）。"""
    current = get_topic(topic_id)
    sets: list[str] = []
    args: list[Any] = []
    if "title" in changes and changes["title"] is not None:
        sets.append("title = ?")
        args.append(validate_title(changes["title"]))
    if "angle" in changes and changes["angle"] is not None:
        sets.append("angle = ?")
        args.append(_validate_angle(changes["angle"]))
    if "status" in changes and changes["status"] is not None:
        if changes["status"] not in STATUS_VALUES:
            raise ValidationError(
                f"status 只允许 {' / '.join(STATUS_VALUES)}",
                detail={"status": changes["status"]},
            )
        sets.append("status = ?")
        args.append(changes["status"])
    if sets:
        sets.append("updated_at = ?")
        args.append(db.utcnow())
        args.append(topic_id)
        with db.db_session() as conn:
            conn.execute(f"UPDATE topics SET {', '.join(sets)} WHERE id = ?", args)
    return current if not sets else get_topic(topic_id)


def delete_topic(topic_id: str) -> dict[str, Any]:
    get_topic(topic_id)  # 不存在 → 404
    with db.db_session() as conn:
        conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))  # scores 级联
    return {"ok": True, "id": topic_id}


def latest_score(topic_id: str) -> dict[str, Any] | None:
    """取最新评分（:mod:`score` 写入后的回读也走这里，口径只有一份）。"""
    return topic_with_score(topic_id)["score"]


# ---------------------------------------------------------------------------
# AI 任务共用路径（SPEC-08 §2）
# ---------------------------------------------------------------------------


async def run_ai_text(*, task: str, prompt: str, profile_id: str | None) -> str:
    """流式收集一轮 AI 文本。空产出按 ``AIOutputInvalid`` 报错，不静默当成功。"""
    profile = profile_store.get_profile(profile_id) if profile_id else None
    harness = get_harness()
    turn_id = uuid.uuid4().hex
    req = TurnRequest(
        session_id=f"topics-{task}-{turn_id[:8]}",
        turn_id=turn_id,
        prompt=prompt,
        profile=profile,
        attachments=[],
        system_suffix=_TASK_SUFFIX,
    )
    parts: list[str] = []
    async for ev in harness.stream(req):
        if ev.type == EventType.TEXT_DELTA:
            parts.append(ev.text())
        elif ev.type == EventType.ERROR:
            raise HarnessError(
                str(ev.data.get("message") or "AI 运行时返回错误"),
                detail={"task": task, "provider_detail": ev.data.get("detail")},
                hint="重试一次；持续失败跑 `atelier doctor` 看运行时诊断",
            )
        elif ev.type == EventType.DONE:
            break
    text = "".join(parts).strip()
    if not text:
        raise AIOutputInvalid("AI 没有返回任何内容", detail={"task": task})
    return text


def extract_json(text: str, *, task: str) -> Any:
    """剥围栏取 JSON（SPEC-08 §2）：首个 ``{`` 到末个 ``}``，失败即 ``AIOutputInvalid``。"""
    t = text.strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        raise AIOutputInvalid(
            f"{task} 的输出里找不到 JSON 对象",
            detail={"task": task, "head": t[:200]},
            hint="重试一次；模型需要输出严格 JSON",
        )
    try:
        return json.loads(t[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AIOutputInvalid(
            f"{task} 的输出不是合法 JSON：{exc.msg}",
            detail={"task": task, "head": t[:200]},
            hint="重试一次；连续失败说明模型不服从 JSON 约定",
        ) from exc


def gates_block_or_raise(text: str, *, what: str) -> dict[str, Any]:
    """AI 文本过 :data:`AI_GATES`；BLOCK 即 ``GateBlocked``（逐项改法随错误体带回）。

    构造走 :meth:`GateBlocked.from_report`——它保证 ``detail.gate_items``
    契约（SPEC-01 §2），改法 hint 也由它从首个失败项取。
    """
    report = run_gates(GateInput.of(text=text), gate_ids=list(AI_GATES))
    payload = report.to_dict()
    if report.blocked:
        failed = [i for i in payload["items"] if not i["passed"] and i["severity"] == "block"]
        raise GateBlocked.from_report(
            report,
            message=f"{what}未通过硬门禁：{'；'.join(i['message'] for i in failed)}",
        )
    return payload
