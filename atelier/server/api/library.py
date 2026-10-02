"""内容库域路由（SPEC-05 §3 · 11 个端点）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/library/projects | 项目列表 + 成品/素材 计数 |
| POST | /api/library/projects | {name} → paths.new_project() |
| GET | /api/library/tree?project=&zone=&sub= | 目录树（面包屑 + 子项） |
| GET | /api/library/files?project=&zone=&kind=&q= | 文件列表（类型过滤 + 名称搜索） |
| GET | /api/library/stream?path= | ★ Range 支持，206 / 200 / 416 |
| GET | /api/library/meta?path= | 文件元信息（size/mime/尺寸/时长） |
| GET | /api/library/preview?path= | 文本类（md/html/srt/json）内容 |
| POST | /api/library/confirm-token | {path} 或 {project} → {token, expires_in, warning} |
| DELETE | /api/library/file?path=&confirm= | 单文件删除（必须带确认口令） |
| DELETE | /api/library/project?project=&confirm= | 整个项目删除（文案含「及其全部内容」） |
| POST | /api/library/unlock-system | 系统文件解锁（M1 只给 UI 提示） |

本模块**只做 HTTP 形状转换**：业务判断全在 :mod:`atelier.server.library.service`，
路径解析全在 :mod:`atelier.server.paths`。按 main.py 的约定，本 router **不写
prefix**（``/api`` 由 ``main._autoload_routers`` 统一加）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from ..errors import ValidationError
from ..library import service
from ..library.service import RangeNotSatisfiable

router = APIRouter(tags=["library"])

__all__ = ["router"]


# ------------------------------------------------------------------ models


class CreateProjectBody(BaseModel):
    name: str


class ConfirmTokenBody(BaseModel):
    """删文件给 ``path``，删项目给 ``project``（二选一，服务层会校验）。"""

    path: str | None = None
    project: str | None = None


class UnlockSystemBody(BaseModel):
    path: str | None = None
    project: str | None = None
    confirm: str = ""


# ------------------------------------------------------------------ 项目


@router.get("/library/projects", summary="项目列表 + 成品/素材计数")
def get_projects() -> dict[str, Any]:
    return service.list_projects()


@router.post("/library/projects", status_code=201, summary="新建项目")
def post_project(body: CreateProjectBody) -> dict[str, Any]:
    return service.create_project(body.name)


# ------------------------------------------------------------------ 浏览


@router.get("/library/tree", summary="目录树（面包屑 + 子项）")
def get_tree(
    project: str = Query(..., description="项目名"),
    zone: str = Query(service.ZONES[0], description="成品 / 素材 / .session"),
    sub: str = Query("", description="zone 之下的子目录，逐级下钻用"),
) -> dict[str, Any]:
    return service.tree(project, zone, sub)


@router.get("/library/files", summary="文件列表（类型过滤 + 名称搜索）")
def get_files(
    project: str = Query(..., description="项目名"),
    zone: str = Query("", description="空 = 整个项目"),
    kind: str = Query("", description="image / video / audio / doc，空 = 全部"),
    q: str = Query("", description="文件名子串搜索，忽略大小写"),
    sub: str = Query(""),
    recursive: bool = Query(True),
) -> dict[str, Any]:
    return service.list_files(project, zone, kind, q, sub, recursive)


# ------------------------------------------------------------------ ★ 流式


@router.get("/library/stream", summary="Range 流式回放（F-G6）")
def stream(
    request: Request,
    path: str = Query(..., description="outputs/ 内相对路径，也接受带 outputs/ 前缀"),
    download: bool = Query(False, description="1 = 作为附件下载"),
) -> Any:
    """正确实现 HTTP Range。

    - 合法 Range（且 If-Range 通过）→ **206** + ``Content-Range`` + ``Accept-Ranges: bytes``
    - 无 Range / If-Range 失配 → **200** + ``Accept-Ranges: bytes``
    - 非法或越界 Range → **416** + ``Content-Range: bytes */<size>``
    - 任意大小都走 :func:`service.iter_file_bytes` 分块迭代，不整读进内存
    """
    try:
        plan = service.stream_plan(
            path,
            range_header=request.headers.get("range"),
            if_range=request.headers.get("if-range"),
            download=download,
        )
    except RangeNotSatisfiable as exc:
        size = exc.detail.get("file_size")
        headers = {"Accept-Ranges": "bytes"}
        if isinstance(size, int):
            headers["Content-Range"] = f"bytes */{size}"
        return JSONResponse(status_code=416, content=exc.to_body(), headers=headers)

    headers = {**plan["headers"], "Content-Type": plan["mime"], "Content-Length": str(plan["length"])}
    return StreamingResponse(
        plan["chunks"](),
        status_code=plan["status"],
        headers=headers,
        media_type=plan["mime"],
    )


@router.get("/library/meta", summary="文件元信息（size / mime / 尺寸 / 时长）")
def get_meta(path: str = Query(...)) -> dict[str, Any]:
    return service.file_meta(path)


@router.get("/library/preview", summary="文本类预览内容（md/html/srt/json）")
def get_preview(path: str = Query(...)) -> dict[str, Any]:
    return service.preview_text(path)


# ------------------------------------------------------------------ 删除保护


@router.post("/library/confirm-token", summary="破坏性操作前置确认口令")
def post_confirm_token(body: ConfirmTokenBody) -> dict[str, Any]:
    """给弹窗用的文案（``warning``）也一起返回，**保证前后端说的是同一句话**。"""
    if body.path and body.project:
        raise ValidationError(
            "一次确认口令只对应一个删除目标",
            detail={"path": body.path, "project": body.project},
            hint="删文件传 path，删项目传 project",
        )
    return service.issue_confirm_token(path=body.path, project=body.project)


@router.delete("/library/file", summary="删除单个文件（必须带 confirm 口令）")
def delete_file(path: str = Query(...), confirm: str | None = Query(None)) -> dict[str, Any]:
    return service.delete_file(path, confirm)


@router.delete("/library/project", summary="删除整个项目（必须带 confirm 口令）")
def delete_project(project: str = Query(...), confirm: str | None = Query(None)) -> dict[str, Any]:
    return service.delete_project(project, confirm)


@router.post("/library/unlock-system", summary="系统文件解锁（M1 只给 UI 提示）")
def post_unlock_system(body: UnlockSystemBody) -> dict[str, Any]:
    return service.unlock_system(body.model_dump())
