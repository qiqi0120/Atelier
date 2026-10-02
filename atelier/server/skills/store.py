"""SPEC-04 §6 · 技能运行记录落库（``skill_runs`` 表）。

**为什么有这层**：M1 之前运行记录只存在 ``api/capability.py`` 的进程内字典里，
进程一重启就丢（产物还在文件系统，但查不到「当时跑了什么、返回码多少、门禁怎么判」）。
这是 M1 验收报告 §6 登记的唯一架构性欠账。

**设计要点**：
- **写穿 + 读缓存**：API 层仍保留进程内字典做在途缓存（轮询在跑的 run 要快），
  但落库是**唯一真相源**；字典未命中就回库查。
- **落库失败不拖垮运行**：产物已经落在文件系统里了，用户真正的工作没丢。
  所以这里捕获异常并 ``log.exception`` 大声记一笔，不把技能运行本身搞挂
  （PRD 原则四「不静默」：必须留日志，不能默默吞）。
- **只存元数据**：产物仍在 ``outputs/``，这里只存索引与结果摘要。
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from atelier.server.core import db

from .runner import RunResult

log = logging.getLogger("atelier.skills.store")

__all__ = ["finish_run", "get_run", "list_runs", "start_run"]

#: 落库的 JSON 字段 ↔ RunResult 属性名
_JSON_FIELDS: tuple[str, ...] = ("params", "artifacts", "gate_report", "cost_estimate", "error", "missing_keys")

_SELECT = """
SELECT id AS run_id, skill_id, project, profile_id, status, params, result_markdown,
       artifacts, gate_report, cost_estimate, cost_actual, stdout, stderr, returncode,
       error, missing_keys, duration, created_at, updated_at
FROM skill_runs
"""


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """行 → API 契约。形状对齐 :meth:`RunResult.to_dict`，前端不用改。"""
    d: dict[str, Any] = dict(row)
    for f in _JSON_FIELDS:
        d[f] = db.loads(d.get(f), None)
    d["duration"] = round(float(d.get("duration") or 0.0), 3)
    d["cost_actual"] = float(d.get("cost_actual") or 0.0)
    return d


def start_run(
    run_id: str,
    skill_id: str,
    *,
    project: str = "default",
    profile_id: str | None = None,
    params: dict[str, Any] | None = None,
) -> None:
    """开跑就落一行 ``status='running'``。

    先落 running 再执行，这样进程被 kill 也留得下一条「跑过但没跑完」的痕迹，
    而不是查无此事。
    """
    now = db.utcnow()
    try:
        with db.db_session() as c:
            c.execute(
                """INSERT OR REPLACE INTO skill_runs
                   (id, skill_id, project, profile_id, status, params, cost_actual, duration,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,0.0,0.0,?,?)""",
                (
                    run_id, skill_id, project, profile_id, "running",
                    db.dumps(params or {}), now, now,
                ),
            )
    except Exception as exc:  # BLE001 不适用：本层已用 log.exception 留痕
        log.exception("skill_runs: 写入 running 记录失败 run_id=%s (%s)", run_id, type(exc).__name__)


def finish_run(result: RunResult, *, profile_id: str | None = None) -> None:
    """运行结束（成功 / 失败 / 缺密钥 / 付费待确认）统一回写终态。"""
    payload = {
        "id": result.run_id,
        "skill_id": result.skill_id,
        "project": result.project or "default",
        "profile_id": profile_id,
        "status": result.status,
        "result_markdown": result.result_markdown,
        "artifacts": db.dumps(result.artifacts),
        "gate_report": db.dumps(result.gate_report),
        "cost_estimate": db.dumps(result.cost_estimate),
        "cost_actual": float(result.cost_actual or 0.0),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "error": db.dumps(result.error),
        "missing_keys": db.dumps(result.missing_keys),
        "duration": float(result.duration or 0.0),
        "updated_at": db.utcnow(),
    }
    try:
        with db.db_session() as c:
            # UPDATE 而非 INSERT OR REPLACE：后者会把 start_run() 落好的 params
            # 整个行替换成空对象，入参就丢了。
            cur = c.execute(
                """UPDATE skill_runs SET
                     skill_id=:skill_id, project=:project, profile_id=:profile_id, status=:status,
                     result_markdown=:result_markdown, artifacts=:artifacts, gate_report=:gate_report,
                     cost_estimate=:cost_estimate, cost_actual=:cost_actual, stdout=:stdout,
                     stderr=:stderr, returncode=:returncode, error=:error,
                     missing_keys=:missing_keys, duration=:duration, updated_at=:updated_at
                   WHERE id=:id""",
                payload,
            )
            if cur.rowcount == 0:
                # wait=True 同步路径不会先 start_run，这行还不存在 → 补插。
                # created_at 用完成时间，此时已经无从得知启动时间。
                c.execute(
                    """INSERT INTO skill_runs
                       (id, skill_id, project, profile_id, status, params, result_markdown,
                        artifacts, gate_report, cost_estimate, cost_actual, stdout, stderr,
                        returncode, error, missing_keys, duration, created_at, updated_at)
                       VALUES (:id,:skill_id,:project,:profile_id,:status,:params,:result_markdown,
                               :artifacts,:gate_report,:cost_estimate,:cost_actual,:stdout,:stderr,
                               :returncode,:error,:missing_keys,:duration,:created_at,:updated_at)""",
                    {**payload, "params": db.dumps({}), "created_at": payload["updated_at"]},
                )
    except Exception as exc:  # 同上：log.exception 已留痕，不拖垮运行
        log.exception("skill_runs: 回写终态失败 run_id=%s (%s)", result.run_id, type(exc).__name__)


def get_run(run_id: str) -> dict[str, Any] | None:
    """查单条运行记录。查不到返回 ``None``（由调用方决定 404 还是 unknown）。"""
    try:
        with db.db_session(commit=False) as c:
            row = c.execute(_SELECT + " WHERE id=?", (run_id,)).fetchone()
        return _row_to_dict(row) if row else None
    except Exception as exc:  # BLE001 不适用：log.exception 已留痕
        log.exception("skill_runs: 查询失败 run_id=%s (%s)", run_id, type(exc).__name__)
        return None


def list_runs(
    *,
    skill_id: str | None = None,
    project: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """运行历史（倒序）。**这是落库真正买到的东西**——重启后仍能查「跑过什么」。"""
    limit = max(1, min(int(limit or 50), 200))
    where: list[str] = []
    args: list[Any] = []
    for col, val in (("skill_id", skill_id), ("project", project), ("status", status)):
        if val:
            where.append(f"{col}=?")
            args.append(val)
    sql = _SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    try:
        with db.db_session(commit=False) as c:
            rows = c.execute(sql, args).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:  # BLE001 不适用：log.exception 已留痕
        log.exception("skill_runs: 列表查询失败 (%s)", type(exc).__name__)
        return []
