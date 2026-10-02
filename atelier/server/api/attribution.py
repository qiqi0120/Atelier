"""归因域路由（SPEC-15 §2，M5）。

CRUD/只读端点同步 def；AI 端点 async。字面路由声明在 ``/{id}`` 之前。
按 main.py 约定不写 prefix（``/api`` 由 ``_autoload_routers`` 统一加）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | /attribution/snapshots | 快照列表 / 手工录入（201） |
| DELETE | /attribution/snapshots/{id} | 删快照 |
| GET | /attribution/growth | F-G30 增长对比（代码算，不足两条 insufficient） |
| POST/GET | /attribution/metrics | F-G31 内容表现录入（201）/ 列表 + 代码聚合 |
| GET | /attribution/records-recent | 最近 20 条发布记录（表现录入下拉数据源） |
| POST | /attribution/roi | F-G34 投入台账录入（201） |
| GET | /attribution/roi/summary | ROI 汇总（无投入 insufficient） |
| POST | /attribution/comments-insight | F-G32 评论洞察（AI，粘贴语料 ≥30 字） |
| POST | /attribution/review | F-G33 内容复盘（AI 诚实模式 + 可选沉淀进画像） |
| POST | /attribution/predict | F-G35 爆款预测（AI，P3 参考性质） |
| POST | /attribution/strategy | F-G36 策略建议（AI 诚实模式） |
| GET | /attribution/workbench-summary | F-H1 工作台概览数据源（SQL 现查） |
| GET | /attribution/dashboard | F-H2 数据看板数据源 |
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..attribution import insights, service

router = APIRouter(tags=["attribution"])

__all__ = ["router"]


# ---------------------------------------------------------------------------
# 请求体
# ---------------------------------------------------------------------------


class SnapshotBody(BaseModel):
    platform: str
    captured_at: str = ""
    followers: int = 0
    likes_total: int = 0
    works_total: int = 0
    note: str = ""


class MetricBody(BaseModel):
    record_id: str
    platform: str
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    collected_at: str = ""
    note: str = ""


class RoiBody(BaseModel):
    hours: float = 0
    amount: float = 0
    record_id: str = ""
    project: str = ""
    note: str = ""


class CommentsBody(BaseModel):
    text: str
    profile_id: str | None = None


class ReviewBody(BaseModel):
    profile_id: str | None = None
    sediment: bool = False


class PredictBody(BaseModel):
    title: str
    body: str
    platform: str
    profile_id: str | None = None


class ProfileBody(BaseModel):
    profile_id: str | None = None


# ---------------------------------------------------------------------------
# 快照 + F-G30 增长对比
# ---------------------------------------------------------------------------


@router.get("/attribution/snapshots", summary="账号快照列表（captured_at 倒序，可按 platform 过滤）")
def get_snapshots(platform: str = "") -> dict[str, Any]:
    return service.list_snapshots(platform=platform)


@router.post("/attribution/snapshots", status_code=201, summary="录入账号快照（手工抄创作中心数字）")
def post_snapshot(body: SnapshotBody) -> dict[str, Any]:
    return service.create_snapshot(
        platform=body.platform, captured_at=body.captured_at, followers=body.followers,
        likes_total=body.likes_total, works_total=body.works_total, note=body.note,
    )


@router.delete("/attribution/snapshots/{sid}", summary="删快照")
def delete_snapshot(sid: str) -> dict[str, Any]:
    return service.delete_snapshot(sid)


@router.get("/attribution/growth", summary="F-G30 增长对比（最近两条快照差值，代码算不调模型）")
def get_growth(platform: str = "", days: int = 0) -> dict[str, Any]:
    return service.growth(platform=platform, days=days)


# ---------------------------------------------------------------------------
# F-G31 内容表现
# ---------------------------------------------------------------------------


@router.get("/attribution/metrics", summary="表现列表 + 代码聚合（platform/days 过滤）")
def get_metrics(platform: str = "", days: int = 0) -> dict[str, Any]:
    return service.list_metrics(platform=platform, days=days)


@router.post("/attribution/metrics", status_code=201, summary="录入单条内容表现（record 必须存在且平台一致）")
def post_metric(body: MetricBody) -> dict[str, Any]:
    return service.create_metric(
        record_id=body.record_id, platform=body.platform, views=body.views,
        likes=body.likes, comments=body.comments, shares=body.shares,
        collected_at=body.collected_at, note=body.note,
    )


@router.get("/attribution/records-recent", summary="最近 20 条发布记录（表现录入下拉数据源）")
def get_records_recent(limit: int = 20) -> dict[str, Any]:
    return service.records_recent(limit=limit)


# ---------------------------------------------------------------------------
# F-G34 ROI
# ---------------------------------------------------------------------------


@router.get("/attribution/roi/summary", summary="ROI 汇总（投入 + 同期产出，全部代码合计）")
def get_roi_summary(days: int = 30) -> dict[str, Any]:
    return service.roi_summary(days=days)


@router.post("/attribution/roi", status_code=201, summary="录入投入台账（hours/amount ≥ 0，至少一项 > 0）")
def post_roi(body: RoiBody) -> dict[str, Any]:
    return service.create_roi(
        hours=body.hours, amount=body.amount, record_id=body.record_id,
        project=body.project, note=body.note,
    )


# ---------------------------------------------------------------------------
# AI 任务（评论洞察 / 复盘 / 预测 / 策略）
# ---------------------------------------------------------------------------


@router.post("/attribution/comments-insight", summary="F-G32 评论洞察（粘贴语料 ≥30 字，不落库）")
async def post_comments_insight(body: CommentsBody) -> dict[str, Any]:
    return await insights.run_comments_insight(text=body.text, profile_id=body.profile_id or None)


@router.post("/attribution/review", summary="F-G33 内容复盘（诚实模式；sediment=true 时沉淀进画像）")
async def post_review(body: ReviewBody) -> dict[str, Any]:
    return await insights.run_review(
        profile_id=body.profile_id or None, sediment=body.sediment
    )


@router.post("/attribution/predict", summary="F-G35 爆款预测（P3 参考性质，响应带固定 notice）")
async def post_predict(body: PredictBody) -> dict[str, Any]:
    return await insights.run_predict(
        title=body.title, body=body.body, platform=body.platform,
        profile_id=body.profile_id or None,
    )


@router.post("/attribution/strategy", summary="F-G36 策略建议（诚实模式，历史聚合注入 prompt）")
async def post_strategy(body: ProfileBody) -> dict[str, Any]:
    return await insights.run_strategy(profile_id=body.profile_id or None)


# ---------------------------------------------------------------------------
# 工作台 / 看板数据源（F-H1 / F-H2，只读）
# ---------------------------------------------------------------------------


@router.get("/attribution/workbench-summary", summary="F-H1 工作台概览数据源（全部 SQL 现查）")
def get_workbench_summary() -> dict[str, Any]:
    return service.workbench_summary()


@router.get("/attribution/dashboard", summary="F-H2 数据看板数据源（快照曲线 + 按天表现 + Top5）")
def get_dashboard(platform: str = "", days: int = 30) -> dict[str, Any]:
    return service.dashboard(platform=platform, days=days)
