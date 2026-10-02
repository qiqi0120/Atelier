"""发现域路由（SPEC-12 §2）。

CRUD 端点同步 def；抓取/AI 端点 async。字面路由一律声明在 ``/{id}`` 之前。
按 main.py 约定不写 prefix（``/api`` 由 ``_autoload_routers`` 统一加）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | /discovery/subscriptions | 订阅列表 / 新建 |
| PATCH/DELETE | /discovery/subscriptions/{id} | 改 / 删（级联删条目） |
| POST | /discovery/subscriptions/{id}/fetch · /ingest · /deep-load | 抓取 / 手填 / 深度加载 |
| POST | /discovery/fetch-all | 全部抓取（部分失败不整批失败） |
| GET | /discovery/feed · /discovery/ugc | feed 列表 / UGC 关键词搜索 |
| GET/POST/PATCH | /discovery/hot(-…) | 素材池 + 日报 + from-feed |
| GET/POST/DELETE | /discovery/algorithm-notes | 算法追踪手工时间线 |
| POST | /discovery/gaps | 内容缺口（无订阅信号不调模型） |
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import errors
from ..discovery import digest, gaps, rss, service

router = APIRouter(tags=["discovery"])

__all__ = ["router"]


# ---------------------------------------------------------------------------
# 请求体
# ---------------------------------------------------------------------------


class SubscriptionBody(BaseModel):
    name: str
    kind: str
    source: str
    url: str | None = None
    platform: str = ""
    keywords: str | list[str] | None = None
    notes: str = ""


class SubscriptionPatch(BaseModel):
    name: str | None = None
    url: str | None = None
    platform: str | None = None
    keywords: str | list[str] | None = None
    notes: str | None = None
    enabled: bool | None = None


class IngestBody(BaseModel):
    title: str
    url: str = ""
    summary: str = ""
    published_at: str = ""


class HotBody(BaseModel):
    title: str
    source: str = "manual"
    platform: str = ""
    url: str = ""
    heat: str = ""
    note: str = ""
    entry_date: str = ""


class HotPatch(BaseModel):
    status: str | None = None
    note: str | None = None


class FromFeedBody(BaseModel):
    ids: list[str] = Field(min_length=1)


class AlgorithmNoteBody(BaseModel):
    platform: str
    noted_at: str
    change: str
    impact: str = ""
    source: str = ""


class GapsBody(BaseModel):
    profile_id: str | None = None
    window_days: int = gaps.WINDOW_DAYS


class DigestBody(BaseModel):
    profile_id: str | None = None


# ---------------------------------------------------------------------------
# 订阅
# ---------------------------------------------------------------------------


@router.get("/discovery/subscriptions", summary="订阅列表")
def get_subscriptions(kind: str = "", source: str = "", enabled: str = "") -> dict[str, Any]:
    enabled_flag: bool | None = None
    if enabled != "":
        if enabled not in ("0", "1"):
            raise errors.ValidationError("enabled 只允许 0 / 1", detail={"enabled": enabled})
        enabled_flag = enabled == "1"
    return service.list_subscriptions(kind=kind, source=source, enabled=enabled_flag)


@router.post("/discovery/subscriptions", status_code=201, summary="新建订阅（rss 必带 URL）")
def post_subscription(body: SubscriptionBody) -> dict[str, Any]:
    return service.create_subscription(
        name=body.name, kind=body.kind, source=body.source, url=body.url,
        platform=body.platform, keywords=body.keywords, notes=body.notes,
    )


@router.patch("/discovery/subscriptions/{sid}", summary="改订阅")
def patch_subscription(sid: str, body: SubscriptionPatch) -> dict[str, Any]:
    return service.update_subscription(sid, body.model_dump(exclude_unset=True))


@router.delete("/discovery/subscriptions/{sid}", summary="删订阅（其 feed 条目级联删除）")
def delete_subscription(sid: str) -> dict[str, Any]:
    return service.delete_subscription(sid)


@router.post("/discovery/subscriptions/{sid}/fetch", summary="抓取单个订阅（关键词+时间窗过滤、去重）")
async def post_subscription_fetch(sid: str) -> dict[str, Any]:
    sub = service.get_subscription(sid)
    return rss.fetch_subscription(sub)


@router.post("/discovery/subscriptions/{sid}/ingest", status_code=201, summary="手填条目（manual 源）")
def post_subscription_ingest(sid: str, body: IngestBody) -> dict[str, Any]:
    return service.ingest_manual(
        sid, title=body.title, url=body.url, summary=body.summary, published_at=body.published_at
    )


@router.post("/discovery/subscriptions/{sid}/deep-load", summary="F-D6 深度加载（诚实模式）")
async def post_subscription_deep_load(sid: str) -> dict[str, Any]:
    """RSS 源：再抓一轮并如实报告（多数 RSS 只提供最新 N 条，不假装能翻历史）；
    manual 源：明确告知不支持自动抓取。"""
    sub = service.get_subscription(sid)
    if sub["source"] != "rss":
        raise service.DiscoveryFetchFailed(
            "手填订阅不支持自动深度加载",
            detail={"subscription_id": sid, "source": sub["source"]},
            hint="手填订阅靠「添加条目」录入内容；要自动抓取请建带 RSS 地址的订阅",
        )
    result = rss.fetch_subscription(sub)
    result["notice"] = (
        "深度加载对 RSS 源是「再抓一轮」：多数源只提供最新若干条，"
        "更早的历史依赖源站归档，本工具不假装能翻页"
    )
    return result


@router.post("/discovery/fetch-all", summary="抓取全部启用的 rss 订阅（逐条回报，部分失败不整批失败）")
async def post_fetch_all() -> dict[str, Any]:
    return rss.fetch_all()


# ---------------------------------------------------------------------------
# feed / UGC
# ---------------------------------------------------------------------------


@router.get("/discovery/feed", summary="feed 条目列表（时间窗默认 7 天）")
def get_feed(
    subscription_id: str = "", q: str = "", days: int = 7, limit: int = 200
) -> dict[str, Any]:
    return service.list_feed(subscription_id=subscription_id, q=q, days=days, limit=limit)


@router.get("/discovery/ugc", summary="F-D13 UGC 发现：订阅内容关键词搜索（标注来源）")
def get_ugc(q: str, days: int = 30, limit: int = 100) -> dict[str, Any]:
    if not q.strip():
        raise errors.ValidationError(
            "搜索词不能为空", hint="输入要找的关键词，如「测评」「开箱」"
        )
    found = service.list_feed(q=q.strip(), days=days, limit=limit)
    return {
        "q": q.strip(),
        "items": found["items"],
        "total": found["total"],
        "notice": "UGC 搜索范围是已订阅源的内容聚合（无平台内搜索数据源）",
    }


# ---------------------------------------------------------------------------
# 热点素材池 / 日报
# ---------------------------------------------------------------------------


@router.get("/discovery/hot", summary="热点素材池")
def get_hot(status: str = "", q: str = "") -> dict[str, Any]:
    return service.list_hot(status=status, q=q)


@router.post("/discovery/hot", status_code=201, summary="手工导入热点素材")
def post_hot(body: HotBody) -> dict[str, Any]:
    return service.create_hot_entry(
        title=body.title, source=body.source, platform=body.platform,
        url=body.url, heat=body.heat, note=body.note, entry_date=body.entry_date,
    )


@router.patch("/discovery/hot/{hid}", summary="改素材（状态归档/备注）")
def patch_hot(hid: str, body: HotPatch) -> dict[str, Any]:
    return service.update_hot_entry(hid, body.model_dump(exclude_unset=True))


@router.post("/discovery/hot/from-feed", summary="feed 条目批量转素材池（去重防重复转入）")
def post_hot_from_feed(body: FromFeedBody) -> dict[str, Any]:
    return service.hot_from_feed(ids=body.ids)


@router.post("/discovery/hot/digest", summary="F-D8 生成热点日报（素材池空时诚实返回，不调模型）")
async def post_hot_digest(body: DigestBody) -> dict[str, Any]:
    return await digest.run_digest(profile_id=body.profile_id or None)


@router.get("/discovery/hot/digests", summary="日报历史")
def get_hot_digests() -> dict[str, Any]:
    return service.list_digests()


@router.get("/discovery/hot/digests/{did}", summary="日报详情")
def get_hot_digest(did: str) -> dict[str, Any]:
    return service.get_digest(did)


# ---------------------------------------------------------------------------
# 算法追踪 / 内容缺口
# ---------------------------------------------------------------------------


@router.get("/discovery/algorithm-notes", summary="F-D12 算法动态追踪（手工时间线）")
def get_algorithm_notes(platform: str = "") -> dict[str, Any]:
    return service.list_algorithm_notes(platform=platform)


@router.post("/discovery/algorithm-notes", status_code=201, summary="登记一条平台规则变化")
def post_algorithm_note(body: AlgorithmNoteBody) -> dict[str, Any]:
    return service.create_algorithm_note(
        platform=body.platform, noted_at=body.noted_at, change=body.change,
        impact=body.impact, source=body.source,
    )


@router.delete("/discovery/algorithm-notes/{nid}", summary="删算法记录")
def delete_algorithm_note(nid: str) -> dict[str, Any]:
    return service.delete_algorithm_note(nid)


@router.post("/discovery/gaps", summary="F-D11 内容缺口分析（无订阅信号不调模型）")
async def post_gaps(body: GapsBody) -> dict[str, Any]:
    return await gaps.run_gaps(
        profile_id=body.profile_id or None, window_days=body.window_days
    )
