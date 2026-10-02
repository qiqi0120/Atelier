"""能力地图 + 技能库 + 密钥配置路由（SPEC-04 §5）。

端点：
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/capabilities      | 4 分组能力地图（无死链） |
| GET | /api/skills            | ?layer= 过滤，**不含 body_markdown** |
| GET | /api/skills/{id}       | 含 SKILL.md 全文 + 配置状态 |
| POST | /api/skills/{id}/run   | {params, project, profile_id, confirm_cost} → {run_id, stream_url} |
| GET | /api/skills/runs/{run_id} | {status, stdout, result_markdown, artifacts[], error} |
| GET | /api/keys              | **只给掩码**，永不返回明文 |
| POST | /api/keys              | 只写；**留空不覆盖** → {"unchanged": true} |
| DELETE | /api/keys/{key_name}  | 清除 |

密钥三条硬规则（PRD F-C9 / F-I4）：只写不回传 / 留空不覆盖 / 存 keychain 降级 secrets.enc。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from atelier.server.errors import SkillMissingKey
from atelier.server.skills import keys, loader, manifest, runner

log = logging.getLogger("atelier.api.capability")

router = APIRouter(prefix="/api", tags=["capability"])

# main.py 的 _autoload_routers 会 `include_router(router, prefix=getattr(mod, "ROUTER_PREFIX", "/api"))`。
# 本 router 自带 `/api` 前缀，若不覆盖就会拼成 `/api/api/skills`（404）。
# 因此显式声明空前缀，让本模块的 `/api` 生效。
ROUTER_PREFIX = ""

# 运行中的任务表。SPEC-01 §8 要求长任务用任务表 + 轮询；M1 先用进程内表，
# 重启后状态丢失（已产物仍在文件系统里）。落库到 core/db.py 属地基域，未在此越界。
_RUNS: dict[str, runner.RunResult] = {}
_RUN_TASKS: dict[str, asyncio.Task] = {}


# ------------------------------------------------------------------ models


class RunBody(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    project: str = "default"
    profile_id: str | None = None
    confirm_cost: bool = False
    wait: bool = False  # 同步等待（调试用；默认走后台任务）


class KeyBody(BaseModel):
    platform: str | None = None
    key_name: str
    value: str = ""


# ------------------------------------------------------------------ 能力地图


@router.get("/capabilities")
def get_capabilities() -> dict:
    """4 个分组，顺序按 capabilities.toml；skill_id 为空的纯对话能力也展示。"""
    return manifest.get_capabilities()


# ------------------------------------------------------------------ 技能库


@router.get("/skills")
def list_skills(layer: str | None = Query(default=None)) -> dict:
    """列表**不含 body_markdown**，避免响应过大（SPEC-04 §5）。"""
    skills = loader.list_skills(layer=layer)
    return {
        "skills": [_skill_brief(s) for s in skills],
        "count": len(skills),
        "layers": loader.LAYERS,
    }


def _skill_brief(s: loader.LoadedSkill) -> dict:
    d = s.model_dump(mode="json")
    d.pop("body_markdown", None)
    d["missing_keys"] = keys.missing_keys(s.required_keys)
    d["runnable"] = not d["missing_keys"]
    return d


@router.get("/skills/runs/{run_id}")
def get_run(run_id: str) -> dict:
    r = _RUNS.get(run_id)
    if r is None:
        return {"run_id": run_id, "status": "unknown", "result_markdown": "", "artifacts": [],
                "error": {"code": "NotFound", "message": f"找不到运行记录 {run_id}"}}
    return r.to_dict()


@router.get("/skills/{skill_id}")
def get_skill(skill_id: str) -> dict:
    """详情抽屉：SKILL.md 全文 + 缺密钥标记（前端据此禁用运行按钮）。"""
    s = loader.get_skill(skill_id)
    missing = keys.missing_keys(s.required_keys)
    d = s.model_dump(mode="json")
    d["missing_keys"] = missing
    d["runnable"] = not missing
    d["block_reason"] = (
        f"缺少 {', '.join(missing)}，运行已禁用" if missing else None
    )
    return d


@router.post("/skills/{skill_id}/run")
async def run_skill(skill_id: str, body: RunBody) -> dict:
    """就地运行。

    **前置检查同步返回**，不藏进后台任务：缺密钥要立刻 409（前端据此禁用运行按钮），
    付费技能未确认要立刻给费用预估（前端据此弹确认框）。只有真正执行才后台化。
    """
    skill = loader.get_skill(skill_id)  # 不存在 → SkillNotFound(404)

    # 1) 缺密钥 → 409，message 写明缺哪个
    missing = keys.missing_keys(skill.required_keys)
    if missing:
        raise SkillMissingKey(
            f"缺少密钥 {', '.join(missing)}，无法运行「{skill.name}」",
            detail={"skill_id": skill_id, "missing_keys": missing,
                    "hint": f"在「{skill.name}」卡片内的「API 配置」里填 {missing[0]}"},
        )

    # 2) 付费技能：先给费用预估，未确认不执行（PRD 原则三）
    if skill.paid and not body.confirm_cost:
        est = runner.estimate_cost(skill, body.params)
        run_id = uuid.uuid4().hex
        log.info("cost gate: %s requires confirmation (¥%.2f)", skill_id, est["amount"])
        return {
            "run_id": run_id,
            "skill_id": skill_id,
            "status": "cost_pending",
            "requires_confirm": True,
            "paid": True,
            "cost_estimate": est,
            "cost_actual": 0.0,
            "artifacts": [],
            "result_markdown": runner.cost_markdown(skill, est),
            "stream_url": f"/api/skills/runs/{run_id}",
        }

    run_id = uuid.uuid4().hex

    async def _job() -> None:
        try:
            r = await runner.run_skill(
                skill_id, body.params, body.project, body.profile_id, confirm_cost=body.confirm_cost
            )
            # ★ 用**端点的 run_id** 入表：runner.run_skill() 内部自己又生成了一个 run_id，
            # 若用 r.run_id 作键，客户端拿到的就是查不到的那一个（status 永远 unknown）。
            r.run_id = run_id
            _RUNS[run_id] = r
        except Exception as e:
            from atelier.server.errors import AtelierError

            err = e.to_dict() if isinstance(e, AtelierError) else {
                "code": "SkillRunFailed", "message": str(e), "detail": None, "hint": None,
            }
            log.exception("skill run failed: %s", skill_id)
            _RUNS[run_id] = runner.RunResult(
                run_id=run_id, skill_id=skill_id, status="failed", project=body.project, error=err
            )

    if body.wait:
        r = await runner.run_skill(
            skill_id, body.params, body.project, body.profile_id, confirm_cost=body.confirm_cost
        )
        _RUNS[r.run_id] = r
        return {**r.to_dict(), "skill_id": skill_id, "stream_url": f"/api/skills/runs/{r.run_id}"}

    task = asyncio.create_task(_job())
    _RUN_TASKS[run_id] = task
    task.add_done_callback(lambda t: _RUN_TASKS.pop(run_id, None))
    return {
        "run_id": run_id,
        "skill_id": skill_id,
        "status": "running",
        "stream_url": f"/api/skills/runs/{run_id}",
        "paid": skill.paid,
        "requires_confirm": False,
    }


# ------------------------------------------------------------------ 密钥


def _all_required_keys() -> set[str]:
    return {k for s in loader.scan().skills for k in s.required_keys}


@router.get("/keys")
def get_keys() -> dict:
    """**只返回掩码**。即使响应体被 grep，也搜不到明文（PRD F-I4）。"""
    infos = keys.list_secrets(extra_keys=_all_required_keys())
    return {
        "keys": [i.to_dict() for i in infos],
        "count": len(infos),
        "required_by_skills": sorted(_all_required_keys()),
        "backend": "keychain" if keys.keyring_backend() is not None else "secrets.enc",
    }


@router.post("/keys")
def set_key(body: KeyBody) -> dict:
    """只写。**留空不覆盖**：空值保持原值并返回 ``unchanged: true``。"""
    if not (body.value or "").strip():
        current = next((i for i in keys.list_secrets(extra_keys={body.key_name})
                        if i.key_name == body.key_name), None)
        log.info("key save skipped (empty value, keep existing): %s", body.key_name)
        return {
            "ok": True,
            "unchanged": True,
            "key_name": body.key_name,
            "masked": current.masked if current else "",
            "message": "未填写新值，保持原有密钥不变",
        }
    info = keys.set_secret(body.key_name, body.value, body.platform)
    log.info("key saved: %s (mask=%s)", body.key_name, info.masked)
    return {"ok": True, "unchanged": False, **info.to_dict()}


@router.delete("/keys/{key_name}")
def delete_key(key_name: str) -> dict:
    removed = keys.delete_secret(key_name)
    log.info("key delete: %s removed=%s", key_name, removed)
    return {"ok": True, "key_name": key_name, "removed": removed}
