"""日历域路由（SPEC-09 §5 · 7 个端点）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/calendar?month=YYYY-MM | 月视图：当月事件 + due_date 落当月的选题 |
| GET | /api/calendar/upcoming?days= | 未来 N 天节点 + 提醒状态（查询式，D5） |
| POST | /api/calendar/seed | 补种内置节点（幂等，D4） |
| POST | /api/calendar/suggest | F-E7 日历建议：AI 生成近 N 天选题并整批落池 |
| POST | /api/calendar | 新建事件（source=manual） |
| PATCH | /api/calendar/{id} | 改事件 |
| DELETE | /api/calendar/{id} | 删事件（内置条目同样可删） |

本模块只做 HTTP 形状转换，业务在 :mod:`atelier.server.calendar`。按 main.py 约定
不写 prefix（``/api`` 由 ``_autoload_routers`` 统一加）。suggest 是真 AI 调用，
端点必须 async；CRUD 同步即可。字面路由（upcoming/seed/suggest）声明在
``/{id}`` 之前（SPEC-09 §5），避免字面量被当 id 吞掉。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..calendar import service, suggest

router = APIRouter(tags=["calendar"])

__all__ = ["router"]


# ------------------------------------------------------------------ models


class CreateEventBody(BaseModel):
    title: str
    date: str
    end_date: str | None = None
    kind: str
    note: str | None = None
    remind_days: int = service.DEFAULT_REMIND


class PatchEventBody(BaseModel):
    title: str | None = None
    date: str | None = None
    end_date: str | None = None
    kind: str | None = None
    note: str | None = None
    remind_days: int | None = None


class SeedBody(BaseModel):
    year: int | None = None


class SuggestBody(BaseModel):
    profile_id: str | None = None
    days: int = suggest.SUGGEST_DEFAULT_DAYS


# ------------------------------------------------------------------ 事件与视图


@router.get("/calendar", summary="月视图（当月事件 + 当月 due_date 选题）")
def get_calendar(month: str = "") -> dict[str, Any]:
    return service.list_month(month=month or "")


@router.get("/calendar/upcoming", summary="未来 N 天节点 + 提醒状态")
def get_upcoming(days: int = 14) -> dict[str, Any]:
    return service.upcoming(days=days)


@router.post("/calendar/seed", summary="补种内置节点（幂等）")
def post_seed(body: SeedBody) -> dict[str, Any]:
    return service.seed(year=body.year)


@router.post("/calendar", status_code=201, summary="新建事件")
def post_event(body: CreateEventBody) -> dict[str, Any]:
    return service.create_event(
        title=body.title,
        date=body.date,
        end_date=body.end_date,
        kind=body.kind,
        note=body.note,
        remind_days=body.remind_days,
    )


@router.patch("/calendar/{event_id}", summary="改事件")
def patch_event(event_id: str, body: PatchEventBody) -> dict[str, Any]:
    return service.update_event(event_id, body.model_dump())


@router.delete("/calendar/{event_id}", summary="删事件（内置条目同样可删）")
def delete_event(event_id: str) -> dict[str, Any]:
    return service.delete_event(event_id)


# ------------------------------------------------------------------ AI 任务


@router.post("/calendar/suggest", status_code=201, summary="F-E7 日历建议（整批落选题池）")
async def post_suggest(body: SuggestBody) -> dict[str, Any]:
    return await suggest.run_suggest(
        profile_id=body.profile_id or None, days=body.days
    )
