"""分析域路由（SPEC-11 §3 + SPEC-12 §3，全部真 AI 调用 → 必须 async）。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/analytics/competitor | F-D10 竞品分析（三列表，不落库） |
| POST | /api/analytics/strategy | F-E12 内容策略（4 段 markdown，不落库） |
| POST | /api/analytics/audience | F-E14 受众画像卡（JSON 卡，不落库） |
| POST | /api/analytics/diagnose | F-E13 账号诊断（诚实模式；记录不足不调模型） |
| POST | /api/analytics/campaign | F-E15 营销活动策划（5 段 markdown，不落库） |
| POST | /api/analytics/liveplan | F-E16 直播策划（5 段 markdown，不落库） |
| POST | /api/analytics/sponsorship | F-E17 品牌合作方案（5 段 markdown，不落库） |

M5 的数据回收端点将来也挂 /analytics 前缀（同文件扩展）。按 main.py 约定不写
prefix（``/api`` 由 ``_autoload_routers`` 统一加）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..insights import audience, campaign, competitor, diagnose, liveplan, sponsorship, strategy

router = APIRouter(tags=["analytics"])

__all__ = ["router"]


class CompetitorBody(BaseModel):
    text: str
    profile_id: str | None = None


class ProfileBody(BaseModel):
    """strategy / audience / diagnose 共用：只有可选画像。"""

    profile_id: str | None = None


class CampaignBody(BaseModel):
    theme: str
    occasion: str = ""
    profile_id: str | None = None


class LiveplanBody(BaseModel):
    topic: str
    duration: str = ""
    profile_id: str | None = None


class SponsorshipBody(BaseModel):
    brief: str
    brand: str = ""
    profile_id: str | None = None


@router.post("/analytics/competitor", summary="F-D10 竞品分析（选题/格式/规律，不落库）")
async def post_competitor(body: CompetitorBody) -> dict[str, Any]:
    return await competitor.run_competitor(text=body.text, profile_id=body.profile_id or None)


@router.post("/analytics/strategy", summary="F-E12 内容策略（4 段 markdown，不落库）")
async def post_strategy(body: ProfileBody) -> dict[str, Any]:
    return await strategy.run_strategy(profile_id=body.profile_id or None)


@router.post("/analytics/audience", summary="F-E14 受众画像卡（不落库）")
async def post_audience(body: ProfileBody) -> dict[str, Any]:
    return await audience.run_audience(profile_id=body.profile_id or None)


@router.post("/analytics/diagnose", summary="F-E13 账号诊断（记录不足时诚实返回，不调模型）")
async def post_diagnose(body: ProfileBody) -> dict[str, Any]:
    return await diagnose.run_diagnose(profile_id=body.profile_id or None)


@router.post("/analytics/campaign", summary="F-E15 营销活动策划（5 段 markdown，不落库）")
async def post_campaign(body: CampaignBody) -> dict[str, Any]:
    return await campaign.run_campaign(
        theme=body.theme, occasion=body.occasion, profile_id=body.profile_id or None
    )


@router.post("/analytics/liveplan", summary="F-E16 直播策划（5 段 markdown，不落库）")
async def post_liveplan(body: LiveplanBody) -> dict[str, Any]:
    return await liveplan.run_liveplan(
        topic=body.topic, duration=body.duration, profile_id=body.profile_id or None
    )


@router.post("/analytics/sponsorship", summary="F-E17 品牌合作方案（5 段 markdown，不落库）")
async def post_sponsorship(body: SponsorshipBody) -> dict[str, Any]:
    return await sponsorship.run_sponsorship(
        brief=body.brief, brand=body.brand, profile_id=body.profile_id or None
    )
