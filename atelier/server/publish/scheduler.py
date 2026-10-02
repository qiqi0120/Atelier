"""M4 · 定时发布调度器（SPEC-14 §0 D3 / F-G20）。

诚实语义：到点触发的是**既有发布编排**（``dispatcher.publish_draft``），
发布本身仍是 dry-run（README 边界：真实发布需真实账号与风控验证）——
调度器解决的是「到点自动跑」，不改变「发出」的模拟性质，结果照常写
``publish_records`` 并带 dry-run 标记。

``run_due`` 是纯函数（测试直接调）；``start_scheduler`` 在 app lifespan
里起后台协程（``ATELIER_SCHEDULER=0`` 关闭）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any

from atelier.server.core import db

from . import dispatcher
from .adapt import PLATFORM_LIMITS

log = logging.getLogger("atelier.publish.scheduler")

__all__ = [
    "INTERVAL_SECONDS",
    "MAX_PER_TICK",
    "SCHEDULER_NOTICE",
    "due_drafts",
    "get_status",
    "run_due",
    "start_scheduler",
]

INTERVAL_SECONDS = 30
#: 单拍最多处理的草稿数（防止堆积时一口气全发）
MAX_PER_TICK = 10

SCHEDULER_NOTICE = (
    "定时发布到点触发的是标准发布流程：校验全部真实执行；"
    "当前真实发布仍为 dry-run（需真实账号与风控验证），记录里带 dry_run 标记"
)

_state: dict[str, Any] = {"last_tick": "", "task": None}


def _draft_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project": row["project"] or "",
        "title": row["title"] or "",
        "body": row["body"] or "",
        "topic_tags": db.loads(row["topic_tags"], []),
        "variants": db.loads(row["variants"], []),
        "attachments": db.loads(row["attachments"], []),
        "topic_id": row["topic_id"] or "",
        "scheduled_date": row["scheduled_date"] or "",
        "created_at": row["created_at"] or db.utcnow(),
        "updated_at": row["updated_at"] or db.utcnow(),
    }


def due_drafts(now: str | None = None) -> list[dict[str, Any]]:
    """到期且调度器尚未触发过的草稿（scheduled_date 升序）。

    「触发过」= 已有任何 publish_records（成功或失败）：调度器对同一排期只开一枪，
    失败的重试走用户手动 retry（F-G18），避免每 30s 对坏草稿反复打记录。
    """
    now = now or db.utcnow()
    with db.db_session(commit=False) as conn:
        rows = conn.execute(
            """SELECT pd.* FROM publish_drafts pd
               WHERE pd.scheduled_date != '' AND pd.scheduled_date <= ?
               AND NOT EXISTS (SELECT 1 FROM publish_records pr WHERE pr.draft_id = pd.id)
               ORDER BY pd.scheduled_date ASC LIMIT ?""",
            (now, MAX_PER_TICK),
        ).fetchall()
    return [_draft_row_to_dict(r) for r in rows]


async def run_due(*, now: str | None = None) -> dict[str, Any]:
    """跑一拍：到期草稿逐个发布（dry-run 语义不变）。返回逐条结果。"""
    now = now or db.utcnow()
    if os.environ.get("ATELIER_SCHEDULER") == "0":
        return {"skipped": True, "reason": "ATELIER_SCHEDULER=0，调度器已停用", "ran": []}
    drafts = due_drafts(now)
    ran: list[dict[str, Any]] = []
    for d in drafts:
        platforms = [v["platform"] for v in d["variants"] if v.get("platform") in PLATFORM_LIMITS]
        if not platforms:
            ran.append({"draft_id": d["id"], "ok": False, "error": "草稿没有任何已适配平台，跳过"})
            continue
        from ..core.models import PublishDraft

        model = PublishDraft(**d)
        try:
            result = await dispatcher.publish_draft(
                model, platforms, None,
                confirm=True,  # 用户此前排期即确认过
                dry_run=True,
                persist=lambda _dd: None,
            )
            _record(d["id"], result)
            ran.append({
                "draft_id": d["id"],
                "title": d["title"],
                "ok": result.ok_count > 0,
                "ok_count": result.ok_count,
                "failed_count": result.failed_count,
                "dry_run": True,
            })
        except Exception as exc:
            log.exception("scheduler publish failed: %s", d["id"])
            ran.append({"draft_id": d["id"], "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    _state["last_tick"] = db.utcnow()
    return {"skipped": False, "count": len(drafts), "ran": ran}


def _record(draft_id: str, result: Any) -> None:
    """调度触发的发布也逐平台写 publish_records（与 API 端点同口径）。"""
    with db.db_session() as conn:
        for r in result.results:
            d = r.to_dict()
            conn.execute(
                "INSERT INTO publish_records (id, draft_id, platform, status, title, error,"
                " error_code, published_url, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    dispatcher.new_record_id(), draft_id, d["platform"], d["status"],
                    "", d["error"], d["error_code"], d["url"], db.utcnow(),
                ),
            )


async def _loop() -> None:
    while True:
        try:
            await run_due()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(INTERVAL_SECONDS)


def start_scheduler() -> bool:
    """lifespan 里调用：返回是否真的启动（ATELIER_SCHEDULER=0 → False）。"""
    if os.environ.get("ATELIER_SCHEDULER") == "0":
        log.info("scheduler disabled via ATELIER_SCHEDULER=0")
        return False
    if _state["task"] is not None:
        return True
    try:
        _state["task"] = asyncio.get_running_loop().create_task(_loop())
    except RuntimeError:
        return False
    log.info("scheduler started (interval=%ss)", INTERVAL_SECONDS)
    return True


async def stop_scheduler() -> None:
    task = _state["task"]
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        _state["task"] = None


def get_status() -> dict[str, Any]:
    now = db.utcnow()
    return {
        "enabled": os.environ.get("ATELIER_SCHEDULER") != "0",
        "interval_seconds": INTERVAL_SECONDS,
        "due_count": len(due_drafts(now)),
        "last_tick": _state["last_tick"],
        "running": _state["task"] is not None,
        "now": now,
        "notice": SCHEDULER_NOTICE,
    }


#: 兼容 datetime 入口（测试方便）
def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
