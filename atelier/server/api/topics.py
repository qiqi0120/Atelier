"""选题域路由（SPEC-08 §5 · 9 个端点）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/topics?profile_id=&status=&q= | 池列表 |
| POST | /api/topics | 新建选题（manual / decode / matrix） |
| GET | /api/topics/{id} | 详情 + 最新评分 |
| PATCH | /api/topics/{id} | 改 title / angle / status |
| DELETE | /api/topics/{id} | 删除（scores 级联） |
| POST | /api/topics/decode | F-E8 爆款拆解（不落库） |
| POST | /api/topics/score | F-E9 选题评分（追加历史） |
| POST | /api/topics/matrix | F-E10 内容矩阵（整批入库） |
| POST | /api/topics/hooks | F-E11 标题 Hook（不落库） |

本模块只做 HTTP 形状转换，业务在 :mod:`atelier.server.topics`。按 main.py 约定
不写 prefix（``/api`` 由 ``_autoload_routers`` 统一加），所以**不需要改 main.py**。
注意：decode/score/matrix/hooks 是真 AI 调用，端点必须是 async；
CRUD 同步即可（FastAPI 会丢线程池）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..topics import decode, hooks, matrix, score, service

router = APIRouter(tags=["topics"])

__all__ = ["router"]


# ------------------------------------------------------------------ models


class CreateTopicBody(BaseModel):
    title: str
    angle: str | None = None
    profile_id: str | None = None
    source: str = "manual"
    source_ref: str | None = None
    decode: str | None = None
    due_date: str | None = None


class PatchTopicBody(BaseModel):
    title: str | None = None
    angle: str | None = None
    status: str | None = None
    due_date: str | None = None


class DecodeBody(BaseModel):
    text: str
    metrics: str = ""
    platform: str = ""
    goal: str = ""
    profile_id: str | None = None


class ScoreBody(BaseModel):
    topic_id: str
    profile_id: str | None = None


class MatrixBody(BaseModel):
    pillars: list[str] = Field(min_length=1)
    formats: list[str] = Field(min_length=1)
    per_combo: int = 2
    profile_id: str | None = None


class HooksBody(BaseModel):
    topic_id: str | None = None
    title: str | None = None
    platform: str = ""
    profile_id: str | None = None


# ------------------------------------------------------------------ 选题池


@router.get("/topics", summary="选题池列表（updated_at 倒序）")
def get_topics(
    profile_id: str = "", status: str = "", q: str = ""
) -> dict[str, Any]:
    return service.list_topics(
        profile_id=profile_id or None, status=status, q=q.strip()
    )


@router.post("/topics", status_code=201, summary="新建选题")
def post_topic(body: CreateTopicBody) -> dict[str, Any]:
    return service.create_topic(
        title=body.title,
        angle=body.angle,
        profile_id=body.profile_id or None,
        source=body.source,
        source_ref=body.source_ref,
        decode=body.decode,
        due_date=body.due_date,
    )


@router.get("/topics/{topic_id}", summary="选题详情 + 最新评分")
def get_topic(topic_id: str) -> dict[str, Any]:
    return service.topic_with_score(topic_id)


@router.patch("/topics/{topic_id}", summary="改选题（title / angle / status / due_date）")
def patch_topic(topic_id: str, body: PatchTopicBody) -> dict[str, Any]:
    return service.update_topic(topic_id, body.model_dump())


@router.delete("/topics/{topic_id}", summary="删除选题（评分级联删除）")
def delete_topic(topic_id: str) -> dict[str, Any]:
    return service.delete_topic(topic_id)


# ------------------------------------------------------------------ AI 任务


@router.post("/topics/decode", summary="F-E8 爆款拆解（6 段式，不落库）")
async def post_decode(body: DecodeBody) -> dict[str, Any]:
    return await decode.run_decode(
        text=body.text,
        metrics=body.metrics,
        platform=body.platform,
        goal=body.goal,
        profile_id=body.profile_id or None,
    )


@router.post("/topics/score", status_code=201, summary="F-E9 选题评分（7 维 + 确定性结论）")
async def post_score(body: ScoreBody) -> dict[str, Any]:
    return await score.run_score(
        topic_id=body.topic_id, profile_id=body.profile_id or None
    )


@router.post("/topics/matrix", status_code=201, summary="F-E10 内容矩阵（整批入库）")
async def post_matrix(body: MatrixBody) -> dict[str, Any]:
    return await matrix.run_matrix(
        pillars=body.pillars,
        formats=body.formats,
        per_combo=body.per_combo,
        profile_id=body.profile_id or None,
    )


@router.post("/topics/hooks", summary="F-E11 标题 Hook（逐条字数校验，不落库）")
async def post_hooks(body: HooksBody) -> dict[str, Any]:
    return await hooks.run_hooks(
        topic_id=body.topic_id or None,
        title=body.title,
        platform=body.platform,
        profile_id=body.profile_id or None,
    )
