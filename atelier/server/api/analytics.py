"""分析域路由（SPEC-11 §3 · 4 个端点，全部真 AI 调用 → 必须 async）。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/analytics/competitor | F-D10 竞品分析（三列表，不落库） |
| POST | /api/analytics/strategy | F-E12 内容策略（4 段 markdown，不落库） |
| POST | /api/analytics/audience | F-E14 受众画像卡（JSON 卡，不落库） |
| POST | /api/analytics/diagnose | F-E13 账号诊断（诚实模式；记录不足不调模型） |

M5 的数据回收端点将来也挂 /analytics 前缀（同文件扩展）。按 main.py 约定不写
prefix（``/api`` 由 ``_autoload_routers`` 统一加）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..insights import audience, competitor, diagnose, strategy

router = APIRouter(tags=["analytics"])

__all__ = ["router"]


class CompetitorBody(BaseModel):
    text: str
    profile_id: str | None = None


class ProfileBody(BaseModel):
    """strategy / audience / diagnose 共用：只有可选画像。"""

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
