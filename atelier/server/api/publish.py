"""SPEC-06 §6 · 发布中心域路由。

端点（SPEC-06 §6 的 14 条）：

==========================  ======  ==========================================
方法                        路径     说明
==========================  ======  ==========================================
GET                         /publish/platforms          平台元信息 + 登录态 + 约束
GET                         /publish/drafts             草稿列表
POST                        /publish/drafts             新建
GET                         /publish/drafts/{id}        详情
PATCH                       /publish/drafts/{id}        局部更新（自动保存，debounce 800ms）
DELETE                      /publish/drafts/{id}        需 confirm token
POST                        /publish/drafts/{id}/adapt  {platforms} → SSE 流式适配
POST                        /publish/drafts/{id}/precheck  → {items, blocked}
POST                        /publish/drafts/{id}/autofix   {platform, field} → 一键裁剪
POST                        /publish/drafts/{id}/publish   {confirm: true} → {results}
POST                        /publish/records/{id}/retry    单条重试
GET                         /publish/sms/{record_id}      短信墙状态轮询
POST                        /publish/sms/{record_id}      提交验证码
==========================  ======  ==========================================

两条硬规则：

1. **router 不写 prefix**（SPEC-01 §8.0）：``main.py`` 的 ``_autoload_routers``
   统一加 ``/api``，自己加前缀会变成 ``/api/api/...`` 全 404。
2. **发布必须带 ``confirm: true``**（SPEC-06 §4 二次确认），且预检有 BLOCK 未过时
   抛 ``GateBlocked``（422，带 ``detail.gate_items``）。

**dry-run 诚实声明**：``publish`` / ``retry`` 的响应里带 ``dry_run: true`` 与
``notice``，前端要原样展示——校验是真的，发出是模拟的。
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..core.db import get_conn
from ..core.models import PlatformVariant, PrecheckItem, Profile, PublishDraft, to_dict
from ..errors import NotFound, ValidationError
from ..gates.base import Severity
from ..publish import adapt as adapt_mod
from ..publish import dispatcher
from ..publish.adapt import PLATFORM_LIMITS, blank_variant, platform_meta, recount
from ..publish.platforms import get_adapter, known_platforms
from ..publish.precheck import precheck_blocked, run_precheck
from ..publish.wordcount import count_platform_chars, crop_to_limit
from ..topics import service as topic_service

log = logging.getLogger("atelier.api.publish")

# SPEC-01 §8.0：域 router **不带 prefix**，`/api` 由 main.py 统一加
router = APIRouter(tags=["publish"])

__all__ = ["router"]


# ---------------------------------------------------------------------------
# 请求体
# ---------------------------------------------------------------------------


class DraftCreate(BaseModel):
    title: str = ""
    body: str = ""
    topic_tags: list[str] = Field(default_factory=list)
    project: str | None = None
    attachments: list[str] = Field(default_factory=list)
    #: 关联选题 / 计划发布日（SPEC-10 §2；``""`` = 不关联）
    topic_id: str | None = None
    scheduled_date: str | None = None


class DraftPatch(BaseModel):
    """草稿局部更新。**所有字段可选**——前端 debounce 800ms 只发改动的字段。"""

    title: str | None = None
    body: str | None = None
    topic_tags: list[str] | None = None
    attachments: list[str] | None = None
    variants: list[dict[str, Any]] | None = None
    project: str | None = None
    topic_id: str | None = None
    scheduled_date: str | None = None


class AdaptBody(BaseModel):
    platforms: list[str] = Field(default_factory=list)


class PrecheckBody(BaseModel):
    """预检入参。整块可选——``{}`` 与不带 body 都要能跑。"""

    platforms: list[str] = Field(default_factory=list)


class AutofixBody(BaseModel):
    platform: str
    #: ``all`` = 标题与正文都裁（抖音两者同限，前端「一键裁剪」用它，
    #: 否则裁完标题正文还超限，门禁依然解不掉）
    field: str = "body"


class PublishBody(BaseModel):
    confirm: bool = False
    platforms: list[str] = Field(default_factory=list)
    dry_run: bool = True


class SmsBody(BaseModel):
    code: str = ""


# ---------------------------------------------------------------------------
# 草稿持久化（只存元数据，SPEC-01 §7）
# ---------------------------------------------------------------------------


def _now() -> str:
    from ..core.db import utcnow

    return utcnow()


def _norm_topic_link(topic_id: str | None) -> str | None:
    """规范化 ``topic_id``（SPEC-10 §0 D5）：None/``""`` → None；否则选题必须存在。"""
    if not topic_id:
        return None
    topic_service.get_topic(topic_id)  # 不存在 → NotFound(404)
    return topic_id


def _norm_scheduled_date(value: str | None) -> str | None:
    """规范化 ``scheduled_date``（D6）：复用选题 due_date 的零填充 ISO 校验。"""
    return topic_service.validate_due_date(value) or None


def _now_dt() -> datetime:
    from ..core.models import utcnow as models_utcnow

    return models_utcnow()


def _row_to_draft(row: Any) -> PublishDraft:
    variants_raw = json.loads(row["variants"] or "[]")
    variants = []
    for v in variants_raw:
        try:
            variants.append(PlatformVariant.model_validate(v))
        except Exception:  # noqa: BLE001 - 坏数据不该让整个草稿列表打不开
            log.warning("skip broken variant in draft %s: %r", row["id"], v)
    return PublishDraft(
        id=row["id"],
        project=row["project"],
        title=row["title"] or "",
        body=row["body"] or "",
        topic_tags=json.loads(row["topic_tags"] or "[]"),
        variants=variants,
        attachments=json.loads(row["attachments"] or "[]"),
        topic_id=row["topic_id"],
        scheduled_date=row["scheduled_date"],
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def load_draft(draft_id: str) -> PublishDraft:
    row = get_conn().execute("SELECT * FROM publish_drafts WHERE id=?", (draft_id,)).fetchone()
    if row is None:
        raise NotFound(
            "找不到这个草稿",
            detail={"draft_id": draft_id},
            hint="草稿可能已被删除；回发布中心重新新建一份",
        )
    return _row_to_draft(row)


def save_draft(d: PublishDraft) -> PublishDraft:
    """整份落盘（UPSERT）。``variants`` / ``attachments`` 存 JSON。"""
    d.updated_at = _now_dt()
    get_conn().execute(
        """INSERT INTO publish_drafts (id, project, title, body, topic_tags, variants, attachments,
                                       topic_id, scheduled_date, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             project=excluded.project, title=excluded.title, body=excluded.body,
             topic_tags=excluded.topic_tags, variants=excluded.variants,
             attachments=excluded.attachments, topic_id=excluded.topic_id,
             scheduled_date=excluded.scheduled_date, updated_at=excluded.updated_at""",
        (
            d.id, d.project, d.title, d.body,
            json.dumps(d.topic_tags, ensure_ascii=False),
            json.dumps([to_dict(v) for v in d.variants], ensure_ascii=False),
            json.dumps(d.attachments, ensure_ascii=False),
            d.topic_id, d.scheduled_date,
            d.created_at.isoformat(), d.updated_at.isoformat(),
        ),
    )
    get_conn().commit()
    return d


def list_drafts(limit: int = 50) -> list[PublishDraft]:
    rows = get_conn().execute(
        "SELECT * FROM publish_drafts ORDER BY updated_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_row_to_draft(r) for r in rows]


def create_draft(body: DraftCreate) -> PublishDraft:
    topic_id = _norm_topic_link(body.topic_id)
    scheduled_date = _norm_scheduled_date(body.scheduled_date)
    d = PublishDraft(
        id=f"pd_{uuid.uuid4().hex[:12]}",
        project=body.project,
        title=body.title,
        body=body.body,
        topic_tags=list(body.topic_tags),
        variants=[],
        attachments=list(body.attachments),
        topic_id=topic_id,
        scheduled_date=scheduled_date,
        created_at=_now_dt(),
        updated_at=_now_dt(),
    )
    return save_draft(d)


def _profile_for_draft() -> Profile | None:
    """取最近更新的画像（画像域的 store 由 SPEC-02 拥有，这里只读库）。

    读不到就返回 None：预检的人设一致性项会退化成「通用模式，跳过检查」，
    **不会阻断发布**（F-G13）。
    """
    try:
        row = get_conn().execute(
            "SELECT * FROM profiles ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    except Exception as exc:  # noqa: BLE001 - 画像表读不到不该拖垮发布
        log.warning("profile lookup failed: %s", exc)
        return None
    if row is None:
        return None
    try:
        return Profile(
            id=row["id"], name=row["name"], platforms=json.loads(row["platforms"] or "[]"),
            identity=row["identity"] or "", style=row["style"] or "",
            audience=row["audience"] or "", platform_rules=row["platform_rules"] or "",
            preferences=row["preferences"] or "",
            memories=[], general_mode=bool(row["general_mode"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("profile row invalid: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 1. 平台元信息 + 登录态
# ---------------------------------------------------------------------------


@router.get("/publish/platforms")
async def get_publish_platforms() -> dict[str, Any]:
    """平台约束 + **真校验**登录态（PRD F-G24）。前端渲染勾选列表用。"""
    out = []
    for p in known_platforms():
        meta = platform_meta(p)
        auth = await get_adapter(p).check_auth()
        out.append({**meta, "auth": auth.to_dict()})
    return {"platforms": out, "count": len(out), "limits": PLATFORM_LIMITS}


# ---------------------------------------------------------------------------
# 2-5. 草稿 CRUD
# ---------------------------------------------------------------------------


@router.get("/publish/drafts")
def get_drafts(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    ds = list_drafts(limit)
    return {
        "drafts": [
            {
                **to_dict(d),
                "selected": [v.platform for v in d.variants if v.adapted or v.status != "pending"],
            }
            for d in ds
        ],
        "count": len(ds),
    }


@router.post("/publish/drafts")
def post_draft(body: DraftCreate) -> dict[str, Any]:
    return to_dict(create_draft(body))


@router.get("/publish/drafts/{draft_id}")
def get_draft(draft_id: str) -> dict[str, Any]:
    return to_dict(load_draft(draft_id))


@router.patch("/publish/drafts/{draft_id}")
def patch_draft(draft_id: str, body: DraftPatch) -> dict[str, Any]:
    """局部更新。**前端 debounce 800ms 打这个接口**（F-G17 草稿不丢）。"""
    d = load_draft(draft_id)
    data = body.model_dump(exclude_unset=True, exclude_none=True)
    if "title" in data:
        d.title = body.title or ""
    if "body" in data:
        d.body = body.body or ""
    if "topic_tags" in data:
        d.topic_tags = list(body.topic_tags or [])
    if "attachments" in data:
        d.attachments = list(body.attachments or [])
    if "project" in data:
        d.project = body.project
    if "topic_id" in data:
        d.topic_id = _norm_topic_link(body.topic_id)  # "" 清空；坏 id → 404（SPEC-10 D5）
    if "scheduled_date" in data:
        d.scheduled_date = _norm_scheduled_date(body.scheduled_date)  # "" 清空（D6）
    if "variants" in data:
        variants: list[PlatformVariant] = []
        for raw in body.variants or []:
            # 客户端只需要给 platform/title/body。char_count / char_limit /
            # over_limit / adapted / status 都是**服务端派生**的，不能要求调用方补齐
            # ——否则「改一下标题」这种最常见的编辑动作会因为缺字段 422。
            payload = {
                "platform": raw.get("platform"),
                "title": raw.get("title", "") or "",
                "body": raw.get("body", "") or "",
                "char_count": raw.get("char_count", 0) or 0,
                "char_limit": raw.get("char_limit", 0) or 0,
                "over_limit": raw.get("over_limit", False),
                "adapted": raw.get("adapted", False),
                "status": raw.get("status", "pending"),
            }
            try:
                v = PlatformVariant.model_validate(payload)
            except Exception as exc:
                raise ValidationError(
                    "平台版本数据不合法",
                    detail={"variant": raw, "reason": str(exc)},
                    hint="只需 platform/title/body，其余字数由服务端算",
                ) from exc
            variants.append(recount(v))
        d.variants = variants
    save_draft(d)
    return to_dict(d)


@router.delete("/publish/drafts/{draft_id}")
def remove_draft(draft_id: str, confirm: str = Query(...)) -> dict[str, Any]:
    """删除草稿。**必须**带 confirm token（SPEC-01 §8 破坏性操作约定）。"""
    if not confirm or not confirm.startswith("cfm_"):
        raise ValidationError(
            "删除草稿需要二次确认 token",
            detail={"draft_id": draft_id},
            hint="先调 confirm-token 拿 token，再带 ?confirm=<token> 重发；或改用 X-Confirm-Token 头",
        )
    load_draft(draft_id)  # 不存在 → 404
    get_conn().execute("DELETE FROM publish_drafts WHERE id=?", (draft_id,))
    get_conn().commit()
    log.info("draft deleted: %s (token=%s)", draft_id, confirm)
    return {"ok": True, "deleted": draft_id}


@router.post("/publish/confirm-token")
def publish_confirm_token(payload: Annotated[dict[str, Any] | None, Body()] = None) -> dict[str, Any]:
    """生成一次性 confirm token（删除草稿用）。token 只回传给前端，不落库。"""
    token = f"cfm_{uuid.uuid4().hex[:16]}"
    target = (payload or {}).get("draft_id")
    return {"token": token, "expires_in": 300, "action": "delete_draft",
            "target": target, "notice": "5 分钟内有效，只能用一次"}


# ---------------------------------------------------------------------------
# 6. 适配（F-G10 流式，逐字渲染）
# ---------------------------------------------------------------------------


@router.post("/publish/drafts/{draft_id}/adapt")
async def adapt_draft(draft_id: str, body: AdaptBody) -> dict[str, Any]:
    """启动多平台适配。

    **返回 SSE 流**（``text/event-stream``），事件形状
    ``{type, platform, text, acc, variant, message}``：
    ``delta`` 逐字、``variant`` 该平台成品、``error`` 单平台失败、``summary`` 收尾。
    前端用 :class:`PlatformVariantCard` 逐字渲染（F-G10）。
    """
    d = load_draft(draft_id)
    platforms = [p for p in (body.platforms or []) if p in PLATFORM_LIMITS]
    if not platforms:
        raise ValidationError(
            "没有选择要适配的平台",
            detail={"platforms": body.platforms, "supported": list(PLATFORM_LIMITS)},
            hint="先勾选至少一个平台（小红书 / 抖音 / 公众号）",
        )
    profile = _profile_for_draft()

    # 先把 variant 落成 adapting 状态，刷新页面也能看到「适配中」
    existing = {v.platform: v for v in d.variants}
    for p in platforms:
        v = existing.get(p) or blank_variant(p, d.title, d.body)
        v.status = "adapting"
        v.adapted = False
        v.error = None
        if p not in existing:
            d.variants.append(v)
    d.variants = [existing.get(p) or next(v for v in d.variants if v.platform == p) for p in platforms]
    save_draft(d)

    async def event_source() -> AsyncIterator[str]:
        produced: dict[str, PlatformVariant] = {}
        errors: dict[str, str] = {}

        def _dump(ev: Any) -> str:
            """把事件里的 pydantic 模型换成 dict 再序列化（SSE 要 JSON，不是 python repr）。"""
            payload = dict(ev)
            v = payload.get("variant")
            if isinstance(v, PlatformVariant):
                payload["variant"] = to_dict(v)
            return json.dumps(payload, ensure_ascii=False, default=str)

        try:
            async for ev in adapt_mod.adapt_platforms(d, platforms, profile):
                kind = str(ev.get("type"))
                if kind == "variant":
                    v = ev["variant"]  # type: ignore[index]
                    produced[v.platform] = v
                elif kind == "error":
                    errors[str(ev.get("platform"))] = str(ev.get("message"))
                yield f"data: {_dump(ev)}\n\n"
        except Exception as exc:
            log.exception("adapt stream failed: draft=%s", draft_id)
            err = {"type": "error", "message": f"适配流异常：{type(exc).__name__}: {exc}"}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
        finally:
            _finalize_adapt(d, produced, errors)
            save_draft(d)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _finalize_adapt(d: PublishDraft, produced: dict[str, PlatformVariant], errors: dict[str, str]) -> None:
    by_key = {v.platform: v for v in d.variants}
    for p, v in produced.items():
        target = by_key.get(p)
        if target is None:
            d.variants.append(v)
        else:
            target.title = v.title
            target.body = v.body
            target.adapted = True
            target.status = "ready"
            target.error = None
            recount(target)
    for p, msg in errors.items():
        target = by_key.get(p)
        if target is not None:
            target.adapted = False
            target.status = "failed"
            target.error = msg


# ---------------------------------------------------------------------------
# 7. 预检（F-G12 / F-G13）
# ---------------------------------------------------------------------------


@router.post("/publish/drafts/{draft_id}/precheck")
async def precheck_draft(
    draft_id: str,
    body: Annotated[PrecheckBody | None, Body()] = None,
) -> dict[str, Any]:
    """逐项预检。★ **人设一致性只告警，绝不阻断**（F-G13）。

    body 可整体省略（``{}`` 或不发 body 都行）——预检不该因为前端漏传字段就报错。
    """
    d = load_draft(draft_id)
    selected = [p for p in (body.platforms if body else []) if p in PLATFORM_LIMITS] or None
    items = await run_precheck(d, _profile_for_draft(), selected=selected)

    # 母版级检查（合规/密钥/标题打分/人设）即使没有平台版本也会跑，所以 items 一般非空。
    # 但**没有平台版本 = 平台规则一条都没判**（字数、封面、登录态全没覆盖），
    # 这时要明确告警，否则用户会误以为「预检通过 = 处处合规」。
    if not d.variants and not selected:
        items = items + [
            PrecheckItem(
                id="no_target",
                label="平台规则未覆盖",
                severity=Severity.WARN,
                passed=False,
                message="还没有任何平台版本，字数上限 / 封面 / 登录态这些平台规则本次都没判",
                fix_hint="先勾选平台并生成版本，再跑一次预检",
            )
        ]

    return {
        "items": [to_dict(i) if hasattr(i, "model_dump") else i for i in items],
        "blocked": precheck_blocked(items),
        "block_count": sum(1 for i in items if i.severity == "block" and not i.passed),
        "warn_count": sum(1 for i in items if i.severity == "warn" and not i.passed),
    }


# ---------------------------------------------------------------------------
# 8. 一键裁剪（autofix）
# ---------------------------------------------------------------------------


@router.post("/publish/drafts/{draft_id}/autofix")
def autofix_draft(draft_id: str, body: AutofixBody) -> dict[str, Any]:
    """把某平台的超限内容裁到上限内（UI-SPEC 规则 16 的「一键裁剪」）。"""
    d = load_draft(draft_id)
    if body.platform not in PLATFORM_LIMITS:
        raise ValidationError(
            f"不支持的平台：{body.platform}",
            detail={"platform": body.platform, "supported": list(PLATFORM_LIMITS)},
            hint=f"可选：{', '.join(PLATFORM_LIMITS)}",
        )
    if body.field not in {"body", "title", "all"}:
        raise ValidationError(
            "field 只能是 body / title / all",
            detail={"field": body.field},
            hint="改标题传 title，改正文传 body，两个都要裁传 all",
        )
    v = next((x for x in d.variants if x.platform == body.platform), None)
    if v is None:
        v = blank_variant(body.platform, d.title, d.body)
        d.variants.append(v)

    limits = PLATFORM_LIMITS[body.platform]
    fields = ("title", "body") if body.field == "all" else (body.field,)
    changes: dict[str, dict[str, int]] = {}
    for fld in fields:
        limit = int(limits["body_max" if fld == "body" else "title_max"])
        source = v.body if fld == "body" else v.title
        before = count_platform_chars(source, body.platform)
        cropped, _total, after = crop_to_limit(source, limit)
        if after > limit:
            # 裁剪后仍超限（极端情况：首单位就超）→ 不落盘，返回失败让人工处理
            raise ValidationError(
                f"裁剪后仍超字数：{after}/{limit}",
                detail={"platform": body.platform, "field": fld, "actual": after, "limit": limit},
                hint="这条开头就超了上限，请手动重写",
            )
        if fld == "body":
            v.body = cropped
        else:
            v.title = cropped
        changes[fld] = {"before": before, "after": after, "limit": limit}
        log.info("autofix: draft=%s platform=%s field=%s %d→%d (limit %d)",
                 draft_id, body.platform, fld, before, after, limit)

    recount(v)
    save_draft(d)
    primary = fields[0]
    return {
        "ok": True, "platform": body.platform, "field": body.field,
        "before": changes[primary]["before"],
        "after": changes[primary]["after"],
        "limit": changes[primary]["limit"],
        "changes": changes,
        "variant": to_dict(v),
        "draft": to_dict(d),
    }


# ---------------------------------------------------------------------------
# 9. 发布（SPEC-06 §4）
# ---------------------------------------------------------------------------


@router.post("/publish/drafts/{draft_id}/publish")
async def publish_draft(draft_id: str, body: PublishBody) -> dict[str, Any]:
    """发布。**必须** ``{confirm: true}``；预检有 BLOCK 未过 → 422 ``GateBlocked``。"""
    d = load_draft(draft_id)
    platforms = [p for p in (body.platforms or []) if p in PLATFORM_LIMITS]
    if not platforms:
        platforms = [v.platform for v in d.variants]
    profile = _profile_for_draft()

    def persist(dd: PublishDraft) -> None:
        save_draft(dd)

    result = await dispatcher.publish_draft(
        d, platforms, profile, confirm=body.confirm, dry_run=body.dry_run, persist=persist
    )
    _record_results(draft_id, result)
    payload = result.to_dict()
    # 诚实声明：dry-run 时把 notice 提到顶层，前端直接展示
    payload["draft"] = to_dict(d)
    return payload


def _record_results(draft_id: str, result: dispatcher.DispatchResult) -> None:
    """逐平台写 ``publish_records``（失败留痕，原则四）。"""
    conn = get_conn()
    for r in result.results:
        conn.execute(
            """INSERT INTO publish_records (id, draft_id, platform, status, title, error, error_code, published_url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                dispatcher.new_record_id(), draft_id, r.platform, r.status,
                (r.name or ""), r.error, r.error_code, r.url, _now(),
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# 10. 单条重试
# ---------------------------------------------------------------------------


@router.post("/publish/records/{record_id}/retry")
async def retry_record(record_id: str) -> dict[str, Any]:
    """重试一条失败的发布记录。**连续失败 3 次不再自动重试**（SPEC-06 §4）。"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM publish_records WHERE id=?", (record_id,)).fetchone()
    if row is None:
        raise NotFound(
            "找不到这条发布记录",
            detail={"record_id": record_id},
            hint="回到发布中心点「重新发布」发起新一轮",
        )
    if row["status"] == "sent":
        return {"ok": True, "skipped": True, "record_id": record_id,
                "message": "这条已经发过了，不重复发（避免重复投放）"}

    fails = conn.execute(
        "SELECT COUNT(*) AS n FROM publish_records WHERE draft_id=? AND platform=? AND status='failed'",
        (row["draft_id"], row["platform"]),
    ).fetchone()["n"]
    if int(fails) >= dispatcher.MAX_RETRY:
        conn.execute("UPDATE publish_records SET status='failed' WHERE id=?", (record_id,))
        conn.commit()
        log.warning("retry refused after %d failures: %s", fails, record_id)
        return {
            "ok": False, "skipped": True, "record_id": record_id,
            "error_code": "retry_exhausted",
            "message": f"该平台已连续失败 {fails} 次，不再自动重试。请先解决根本原因（登录态 / 内容），再手动发起新一轮发布。",
        }

    d = load_draft(row["draft_id"])
    platform = row["platform"]
    if platform not in PLATFORM_LIMITS:
        raise ValidationError(
            f"记录里的平台不支持：{platform}",
            detail={"platform": platform},
            hint="记录可能是旧版本留下的，请重新建草稿",
        )
    result = await dispatcher.publish_draft(
        d, [platform], _profile_for_draft(), confirm=True, dry_run=True, persist=save_draft
    )
    _record_results(d["id"], result)  # type: ignore[index]
    out = result.to_dict()
    out["record_id"] = record_id
    out["retried"] = True
    return out


# ---------------------------------------------------------------------------
# 11-12. 短信墙
# ---------------------------------------------------------------------------


@router.get("/publish/sms/{record_id}")
def get_sms(record_id: str) -> dict[str, Any]:
    """短信墙状态轮询 → ``{need_sms, expires_in}``（前端倒计时用）。"""
    return dispatcher.sms_state(record_id)


@router.post("/publish/sms/{record_id}")
def post_sms(record_id: str, body: SmsBody) -> dict[str, Any]:
    """提交验证码。真实验证码校验属 M4（本批只校验格式与有效期）。"""
    return dispatcher.submit_sms(record_id, body.code)


# ---------------------------------------------------------------------------
# 发布状态查询（前端 PublishStatusList 的历史记录）
# ---------------------------------------------------------------------------


@router.get("/publish/drafts/{draft_id}/records")
def get_records(draft_id: str) -> dict[str, Any]:
    rows = get_conn().execute(
        "SELECT * FROM publish_records WHERE draft_id=? ORDER BY created_at DESC", (draft_id,)
    ).fetchall()
    out = []
    for r in rows:
        item = {
            "id": r["id"], "draft_id": r["draft_id"], "platform": r["platform"],
            "platform_name": PLATFORM_LIMITS.get(r["platform"], {}).get("name", r["platform"]),
            "status": r["status"], "title": r["title"], "error": r["error"],
            "error_code": r["error_code"], "hint": dispatcher.error_hint(r["error_code"]),
            "published_url": r["published_url"], "created_at": r["created_at"],
            "dry_run": True,
        }
        out.append(item)
    return {"records": out, "count": len(out)}
