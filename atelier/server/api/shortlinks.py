"""M4 · 短链管理路由（SPEC-14 §1.2）。跳转路由 ``GET /s/{code}`` 在 main.py（根路径）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..shortlinks import service

router = APIRouter(tags=["shortlinks"])

__all__ = ["router"]


class ShortlinkBody(BaseModel):
    target: str
    note: str = ""


@router.post("/shortlinks", status_code=201, summary="F-G21 生码（同目标幂等复用）")
def post_shortlink(body: ShortlinkBody) -> dict[str, Any]:
    return service.create_shortlink(target=body.target, note=body.note)


@router.get("/shortlinks", summary="短链列表（含 hits 计数）")
def get_shortlinks() -> dict[str, Any]:
    return service.list_shortlinks()
