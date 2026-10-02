"""SPEC-02 §5 · 账号画像路由（13 个端点）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/profiles | 列表（含 completeness），按 updated_at 倒序 |
| POST | /api/profiles | 新建 `{name, platforms}` → 带 `wizard_token` 的空画像 |
| GET | /api/profiles/{id} | 详情 |
| PATCH | /api/profiles/{id} | 局部更新任一维，自动重算 completeness |
| DELETE | /api/profiles/{id} | 需 `?confirm=<token>`；**有会话引用时 409** |
| POST | /api/profiles/{id}/wizard/step | `{step, data}` → `{next_step, progress}`；`step: done` 结束 |
| DELETE | /api/profiles/{id}/wizard | 中途放弃，保留已填内容 |
| GET | /api/profiles/{id}/memories | 记忆列表 |
| POST | /api/profiles/{id}/memories | 手动加记忆 `{text}` |
| DELETE | /api/profiles/{id}/memories/{mid} | |
| POST | /api/profiles/{id}/general-mode | `{enabled}` 切通用模式 |
| GET | /api/profiles/{id}/export | 下载 `.md` |
| GET | /api/profiles/{id}/preview | 预览渲染后的 `system_prompt`（调试用） |

**``/preview`` 是本域最重要的调试端点**：它调的是
:func:`prompt.build_system_prompt`——和真正发进 harness 的那条路径同一个函数。
因此「预览里看见了」就等于「这一轮真的注入了」，验收 3/4/5 全靠它。

路由按 spec 只写子路径：``/api`` 前缀由 ``main.py`` 的 ``_autoload_routers`` 统一加。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from atelier.server.errors import ValidationError
from atelier.server.profile import prompt as prompt_mod
from atelier.server.profile import store, wizard

log = logging.getLogger("atelier.api.profile")

# 注意：不写 prefix。main.py 的 _autoload_routers 会统一加 /api。
router = APIRouter(tags=["profile"])


# ------------------------------------------------------------------ 请求体


class CreateBody(BaseModel):
    name: str
    platforms: list[str] = Field(default_factory=list)
    # 直接带上已有的维度内容（前端「不用向导，直接建」时用）
    fields: dict[str, str] = Field(default_factory=dict)


class PatchBody(BaseModel):
    name: str | None = None
    platforms: list[str] | None = None
    identity: str | None = None
    style: str | None = None
    audience: str | None = None
    platform_rules: str | None = None
    preferences: str | None = None
    general_mode: bool | None = None

    def changes(self) -> dict[str, Any]:
        """只把**显式给了**的字段交下去。None 一律当「没这个字段」，
        这样 PATCH 不会把没传的维度清空。"""
        out: dict[str, Any] = {}
        for key in store.PROFILE_FIELDS:
            val = getattr(self, key, None)
            if val is not None:
                out[key] = val
        return out


class WizardStepBody(BaseModel):
    step: str
    data: dict[str, Any] = Field(default_factory=dict)
    skip: bool = False
    # 建向导时拿到的 token。刷新页面丢了它就传 GET /wizard 拿回来的那个
    token: str | None = None


class MemoryBody(BaseModel):
    text: str
    source: str = "手动"


class GeneralModeBody(BaseModel):
    enabled: bool


# ------------------------------------------------------------------ 画像 CRUD


@router.get("/profiles", summary="画像列表（含六维完整度）")
def list_profiles() -> dict[str, Any]:
    """按 ``updated_at`` 倒序。响应只给摘要，不塞六维正文。"""
    store.ensure_synced()
    items = store.list_profiles()
    return {
        "profiles": [store.wizard_marker(p) for p in items],
        "count": len(items),
        "dimensions": list(store.TEXT_DIMS) + ["memories"],
    }


@router.post("/profiles", status_code=201, summary="新建画像（只有名字也能建）")
def create_profile(body: CreateBody) -> dict[str, Any]:
    """返回带 ``wizard_token`` 的空画像——前端拿它直接开 4 步向导。"""
    store.ensure_synced()
    profile = store.create_profile(body.name, body.platforms, fields=body.fields)
    token = wizard.create_token(profile.id, profile_name=profile.name)
    log.info("profile created: %s (%s)", profile.id, profile.name)
    data = store.profile_dict(profile)
    data["wizard_token"] = token
    data["wizard"] = {
        "token": token,
        "steps": [wizard.step_meta(k) for k in wizard.STEP_KEYS],
        "next_step": wizard.STEP_KEYS[0],
        "progress": 0,
        "progress_label": "0/4",
    }
    return data


@router.get("/profiles/{profile_id}", summary="画像详情")
def get_profile(profile_id: str) -> dict[str, Any]:
    store.ensure_synced()
    return store.profile_dict(store.get_profile(profile_id))


@router.patch("/profiles/{profile_id}", summary="局部更新任一维，自动重算完整度")
def patch_profile(profile_id: str, body: PatchBody) -> dict[str, Any]:
    changes = body.changes()
    if not changes:
        # 空 PATCH 不当成错误：返回当前状态，前端可以直接拿它刷新缓存
        return store.profile_dict(store.get_profile(profile_id))
    profile = store.update_profile(profile_id, changes)
    log.info("profile updated: %s fields=%s", profile_id, sorted(changes))
    return store.profile_dict(profile)


@router.delete("/profiles/{profile_id}", summary="删画像（有会话引用时 409）")
def delete_profile(profile_id: str, confirm: str | None = Query(default=None)) -> dict[str, Any]:
    """``?confirm=<profile_id>`` 二次确认（UI-SPEC 规则 19）。"""
    store.delete_profile(profile_id, confirm=confirm)
    log.info("profile deleted: %s", profile_id)
    return {"ok": True, "deleted": profile_id}


# ------------------------------------------------------------------ 创建向导


@router.get("/profiles/{profile_id}/wizard", summary="读取向导进度（中途退出后恢复）")
def get_wizard(profile_id: str, token: str = Query(...)) -> dict[str, Any]:
    """带 token 回来就接着走。token 过期 → 422，提示重建。"""
    store.get_profile(profile_id)
    state = wizard.get_state(token)
    if state.profile_id != profile_id:
        raise ValidationError(
            "向导进度和画像对不上",
            detail={"token": token, "expect_profile": state.profile_id, "got_profile": profile_id},
            hint="这个 token 属于另一个画像；回到该画像重新取 token",
        )
    return {**state.to_dict(), "steps": [wizard.step_meta(k) for k in wizard.STEP_KEYS]}


@router.post("/profiles/{profile_id}/wizard/step", summary="走一步（每步都可跳过，跳过也前进）")
def wizard_step(profile_id: str, body: WizardStepBody) -> dict[str, Any]:
    store.get_profile(profile_id)
    token = _token_for(profile_id, body)
    state = wizard.advance(token, body.step, body.data, skip=body.skip)
    result = state.to_dict()
    result["step"] = body.step
    result["skipped_now"] = body.step in state.skipped
    result["profile"] = store.profile_dict(store.get_profile(profile_id))
    log.info(
        "wizard: profile=%s step=%s progress=%s skipped=%s",
        profile_id, body.step, result["progress_label"], state.skipped,
    )
    return result


@router.delete("/profiles/{profile_id}/wizard", summary="中途放弃（已填内容保留）")
def abandon_wizard(profile_id: str, token: str = Query(...)) -> dict[str, Any]:
    store.get_profile(profile_id)
    result = wizard.abandon(token)
    result["profile"] = store.profile_dict(store.get_profile(profile_id))
    return result


def _token_for(profile_id: str, body: WizardStepBody) -> str:
    """取向导 token。缺了就现开一个。

    现开一个是刻意的：前端中途刷新丢了 token 时不该整条链路卡死，
    而「最多少收集一点」比「报错让用户重开一遍」友好得多（spec 的目标是 < 3 分钟）。
    """
    token = (body.token or "").strip()
    if token:
        return token
    return wizard.create_token(profile_id)


# ------------------------------------------------------------------ 长期记忆


@router.get("/profiles/{profile_id}/memories", summary="长期记忆列表")
def list_memories(profile_id: str) -> dict[str, Any]:
    memories = store.list_memories(profile_id)
    return {
        "memories": [m.model_dump(mode="json") for m in memories],
        "count": len(memories),
    }


@router.post("/profiles/{profile_id}/memories", status_code=201, summary="手动加一条记忆")
def add_memory(profile_id: str, body: MemoryBody) -> dict[str, Any]:
    """下一轮对话立即生效——记忆直接进 :func:`prompt.build_profile_prefix`。"""
    memory = store.add_memory(profile_id, body.text, source=body.source)
    return {"ok": True, "memory": memory.model_dump(mode="json"),
            "message": "已记住，下一轮对话生效"}


@router.delete("/profiles/{profile_id}/memories/{memory_id}", summary="删一条记忆")
def delete_memory(profile_id: str, memory_id: str) -> dict[str, Any]:
    store.delete_memory(profile_id, memory_id)
    return {"ok": True, "deleted": memory_id}


# ------------------------------------------------------------------ 通用模式


@router.post("/profiles/{profile_id}/general-mode", summary="切通用模式（开启后完全不注入画像）")
def general_mode(profile_id: str, body: GeneralModeBody) -> dict[str, Any]:
    profile = store.set_general_mode(profile_id, body.enabled)
    log.info("general_mode: profile=%s enabled=%s", profile_id, body.enabled)
    data = store.profile_dict(profile)
    data["message"] = (
        "已切到通用模式：这一轮开始不注入画像，随时可以切回来"
        if body.enabled
        else "已切回画像模式：下一轮对话立即按画像产出"
    )
    return data


# ------------------------------------------------------------------ 导出 / 预览


@router.get("/profiles/{profile_id}/export", summary="导出画像 .md")
def export_profile(profile_id: str) -> Response:
    """下载 ``profiles/<id>.md`` 的内容（人可读、可进版本库）。"""
    profile = store.get_profile(profile_id)
    body = store.render_markdown(profile)
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{profile.id}.md"'},
    )


@router.get("/profiles/{profile_id}/preview", summary="预览渲染后的 system_prompt（调试用）")
def preview_profile(profile_id: str) -> dict[str, Any]:
    """**这是验证「画像真的注入了」的唯一手段**（验收 3/4/5）。

    ``system_prompt`` 走的是 :func:`prompt.build_system_prompt`——
    与真正发进 harness 的字符串同一条代码路径，不是另拼一份给人看的。
    """
    profile = store.get_profile(profile_id)
    system_prompt = prompt_mod.build_system_prompt(profile)
    prefix = prompt_mod.build_profile_prefix(profile)
    return {
        "profile_id": profile.id,
        "system_prompt": system_prompt,
        "prefix": prefix,
        "base": prompt_mod.BASE_SYSTEM_PROMPT,
        "suffix": prompt_mod.build_turn_suffix(),
        "general_mode": profile.general_mode,
        "completeness": profile.completeness(),
        **prompt_mod.describe_injection(profile),
        "leaked_dims": leaked_dims(system_prompt, profile),
    }


def leaked_dims(system_prompt: str, profile: Any) -> list[str]:
    """自检：**该没注入时**，拼好的 ``system_prompt`` 里有没有混进画像正文。

    验收 3（通用模式不含任何画像内容）靠这个字段机器判定，不用人眼扫 prompt。
    正常模式（画像本就该注入）恒返回空数组——否则它就变成「有画像就报错」了。
    """
    if prompt_mod.build_profile_prefix(profile):
        return []  # 正常模式：画像在 prompt 里是设计如此，不算泄漏
    hits: list[str] = []
    for dim in store.TEXT_DIMS:
        body = (getattr(profile, dim, "") or "").strip()
        if body and body in system_prompt:
            hits.append(dim)
    for m in getattr(profile, "memories", []) or []:
        if m.adopted and m.text.strip() and m.text.strip() in system_prompt:
            hits.append("memories")
            break
    return hits
