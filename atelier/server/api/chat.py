"""SPEC-03 §3/§4/§5 · 对话工作台路由。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/chat/stream | 开一轮 → SSE（冲突 409 SessionBusy） |
| POST | /api/chat/interrupt | 中断，**2s 内**界面停止（F-B5） |
| GET | /api/chat/turn/{turn_id} | ``{events, status}`` 断线恢复补齐（F-B6） |
| GET | /api/chat/turn/{turn_id}/stream | 断线重连用 SSE（重放 backlog + 接实时队列） |
| POST | /api/chat/answer | 问答题作答 → 记答案并继续生成（F-B7） |
| GET/POST | /api/chat/sessions | 分组列表 / 新建 |
| PATCH | /api/chat/sessions/{id} | 重命名 / 归档切换 |
| POST | /api/chat/sessions/{id}/archive | 归档 |
| DELETE | /api/chat/sessions/{id} | 需 ``?confirm=<token>`` |
| GET | /api/chat/sessions/{id}/messages | 分页倒序 + 问答题状态 |
| POST | /api/chat/upload | 素材上传（≤200MB + 类型白名单） |
| POST | /api/chat/confirm-token | 破坏性操作的二次确认 token |
| GET | /api/chat/active | 当前活跃 turn（诊断 / 多窗口排查用） |

**路由前缀**：本模块的 ``router`` **不带** prefix，``/api`` 由 ``main.py`` 统一加
（SPEC-01 §8.0；带前缀会变成 ``/api/api/chat/...`` 全 404）。

三条硬验收对应关系：

- 断线不丢（F-B6）→ ``/turn/{id}`` 读 ``<turn_id>.stream.jsonl``，事件带 ``index`` 供去重
- 2s 内停止（F-B5）→ ``/interrupt`` 先 ``Task.cancel()`` 再 ``harness.interrupt()``
- 问答题不重复（F-B7）→ ``manager._is_duplicate_question`` 在服务端丢弃已答 ``question_id``
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from atelier.server import paths
from atelier.server.core import models
from atelier.server.errors import AtelierError, NotFound, ValidationError
from atelier.server.harness.base import TurnEvent
from atelier.server.sessions import manager as mgr
from atelier.server.sessions import store
from atelier.server.sessions.sse import KEEPALIVE_SECONDS, format_comment, sse_response

log = logging.getLogger("atelier.api.chat")

#: SPEC-01 §8.0：**不要**写 prefix，main.py 统一加 /api
router = APIRouter(tags=["chat"])

#: 破坏性操作 confirm token 的有效期（秒）
CONFIRM_TTL = 600
_CONFIRM_SECRET = secrets.token_bytes(32)

#: 每次上传的分块读写大小
UPLOAD_CHUNK = 1024 * 1024


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class AttachmentIn(BaseModel):
    """客户端回传的附件引用。

    ``path`` 必须是工作台自己产出的 ``outputs/...`` 相对路径；服务端会用
    ``paths.resolve_inside(ROOT, path)`` 复核存在性，**不信任**客户端给的路径
    （否则等于让前端把任意系统路径塞进 agent 的上下文）。
    """

    id: str | None = None
    kind: Literal["image", "video", "audio", "doc"] = "doc"
    path: str
    name: str = ""
    size: int = 0
    mime: str = ""


class StreamBody(BaseModel):
    session_id: str
    text: str = ""
    attachments: list[AttachmentIn] = Field(default_factory=list)
    profile_id: str | None = None
    project: str | None = None
    client_id: str = "anonymous"
    system_suffix: str | None = None


class AnswerBody(BaseModel):
    session_id: str
    question_id: str
    option_key: str
    option_label: str | None = None


class InterruptBody(BaseModel):
    turn_id: str


class CreateSessionBody(BaseModel):
    title: str | None = None
    profile_id: str | None = None


class PatchSessionBody(BaseModel):
    title: str | None = None
    archived: bool | None = None
    profile_id: str | None = None


class ConfirmTokenBody(BaseModel):
    action: Literal["delete-session"] = "delete-session"
    id: str


# ---------------------------------------------------------------------------
# 上传不合规 → 400（SPEC-03 §4）
# ---------------------------------------------------------------------------


class UploadRejected(ValidationError):
    """上传被拒 → **400** + 统一错误体 + 明确原因。

    ``errors.py`` 里 :class:`ValidationError` 是 422，而 SPEC-03 §4 要求
    「其余 400 并说明原因」。这里只覆写 ``http``，``code``/响应体形状保持
    SPEC-01 §2 冻结的 ``{code,message,detail,hint}``，前端仍按 ``code`` 分支。
    统一异常处理器 ``register_exception_handlers`` 认 ``AtelierError`` 子类并读
    ``exc.http``，所以不需要额外注册路由级 handler。
    """

    code = "ValidationError"
    http = 400


# ---------------------------------------------------------------------------
# confirm token（SPEC-01 §8.1）
# ---------------------------------------------------------------------------


def _sign(action: str, target: str, exp: int) -> str:
    return hmac.new(_CONFIRM_SECRET, f"{action}|{target}|{exp}".encode(), hashlib.sha256).hexdigest()


def _issue_token(action: str, target: str) -> dict[str, Any]:
    exp = int(time.time()) + CONFIRM_TTL
    return {
        "token": f"{exp}.{_sign(action, target, exp)}",
        "action": action,
        "id": target,
        "expires_at": exp,
        "ttl": CONFIRM_TTL,
    }


def _require_token(action: str, target: str, token: str | None) -> None:
    if not token:
        raise ValidationError(
            "缺少 confirm token",
            detail={"action": action, "id": target},
            hint=f"先调 POST /api/chat/confirm-token {{action:'{action}', id:'{target}'}}，再带 ?confirm=",
        )
    raw_exp, _, sig = token.partition(".")
    try:
        exp = int(raw_exp)
    except ValueError as exc:
        raise ValidationError("confirm token 格式不对", detail={"token": token}, hint="重新申请一个") from exc
    if exp < int(time.time()):
        raise ValidationError(
            "confirm token 已过期",
            detail={"action": action, "id": target, "expired_at": exp},
            hint=f"超过 {CONFIRM_TTL}s 需重新申请",
        )
    if not hmac.compare_digest(sig, _sign(action, target, exp)):
        raise ValidationError(
            "confirm token 不匹配",
            detail={"action": action, "id": target},
            hint="token 是给别的对象签的，重新申请",
        )


# ---------------------------------------------------------------------------
# SSE 数据源
# ---------------------------------------------------------------------------


async def _stream_with_keepalive(source: AsyncIterator[TurnEvent]) -> AsyncIterator[Any]:
    """在事件流上加保活注释帧（``KEEPALIVE_SECONDS`` 无事件就发一次）。

    不用「轮询文件」：数据来自 manager 的内存队列，注释帧只是防中间层掐空闲连接。
    """
    it = source.__aiter__()
    pending: asyncio.Task[TurnEvent] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(it.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=KEEPALIVE_SECONDS)
            if not done:
                yield format_comment("keep-alive")
                continue
            try:
                ev = pending.result()
            except StopAsyncIteration:
                return
            finally:
                pending = None
            yield ev
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
        aclose = getattr(it, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:  # noqa: BLE001,S110 - 关闭流时的异常不该影响响应收尾
                pass


def _sse(turn_id: str) -> StreamingResponse:
    return sse_response(
        _stream_with_keepalive(mgr.get_manager().events(turn_id)),
        headers={"X-Atelier-Turn-Id": turn_id},
    )


# ---------------------------------------------------------------------------
# 轮次
# ---------------------------------------------------------------------------


@router.post("/chat/stream", summary="发一轮（SSE 流式；会话被占用时 409）")
async def chat_stream(body: StreamBody) -> StreamingResponse:
    """发一轮并流式返回。

    409 一定**在开流之前**抛出（前端才能弹「已被其他窗口占用 → 自动开新会话」）；
    一旦返回了 200，响应就已经是 ``text/event-stream``，后面只能靠 error 事件。
    """
    session = store.get_session(body.session_id)
    text = (body.text or "").strip()
    attachments = _validate_attachments(body.attachments)

    if text:
        store.add_message(session.id, "user", text, attachments=attachments)
    _autotitle(session, text, attachments)

    turn_id = store.new_id("t")
    manager = mgr.get_manager()
    profile = mgr.load_profile(body.profile_id)
    req = manager.build_request(
        session_id=session.id,
        turn_id=turn_id,
        text=text,
        profile=profile,
        attachments=attachments,
        project=body.project,
        system_suffix=body.system_suffix,
    )
    # SessionBusy（409）在这里抛，StreamingResponse 还没构造 → 统一错误体直达浏览器
    await manager.start(req, client_id=body.client_id, profile_id=body.profile_id)
    log.info("turn 启动：session=%s turn=%s client=%s", session.id, turn_id, body.client_id)
    return _sse(turn_id)


@router.post("/chat/interrupt", summary="中断当前轮（2s 内生效）")
async def chat_interrupt(body: InterruptBody) -> dict[str, Any]:
    """先 ``Task.cancel()``，再 ``harness.interrupt()`` 兜底（SPEC-01 §3）。"""
    paths.validate_id(body.turn_id, "turn_id")
    t0 = time.monotonic()
    result = await mgr.get_manager().interrupt(body.turn_id)
    result["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    log.info("turn 中断：turn=%s 用时 %dms", body.turn_id, result["elapsed_ms"])
    return result


@router.get("/chat/turn/{turn_id}", summary="取该轮全部事件（断线恢复）")
async def get_turn(turn_id: str) -> dict[str, Any]:
    """``{events, status}``；事件带 ``data.index``（0 起），前端据此去重。"""
    result = await mgr.get_manager().resume(turn_id)
    if not result["events"] and not mgr.get_manager().status(turn_id):
        raise NotFound(
            "找不到这一轮的记录",
            detail={"turn_id": turn_id},
            hint="它可能还没开始落盘，或属于另一个进程；刷新会话列表看看",
        )
    return result


@router.get("/chat/turn/{turn_id}/stream", summary="断线重连用 SSE（重放 + 接实时）")
async def reattach_turn_stream(turn_id: str) -> StreamingResponse:
    """**GET** 形态的 SSE，前端 ``EventSource`` 断线重连走这里。

    与 ``POST /chat/stream`` 的区别：不新建轮次，只是把该轮已产生的事件重放一遍
    再接上实时队列——所以「断网 10 秒后恢复」不会重复生成，也不会丢内容。
    """
    paths.validate_id(turn_id, "turn_id")
    return _sse(turn_id)


@router.post("/chat/answer", summary="回答问答题（记答案并继续生成）")
async def chat_answer(body: AnswerBody) -> StreamingResponse:
    """F-B7：答案进 ``answered_questions``，选项文案作为新的 user message 继续生成。"""
    session = store.get_session(body.session_id)
    paths.validate_id(body.question_id, "question_id")
    manager = mgr.get_manager()
    label = body.option_label or manager.option_label(session.id, body.question_id, body.option_key)
    manager.mark_answered(session.id, body.question_id, body.option_key, label)

    store.add_message(session.id, "user", label)
    turn_id = store.new_id("t")
    req = manager.build_request(
        session_id=session.id,
        turn_id=turn_id,
        text=label,
        profile=mgr.load_profile(session.profile_id),
        project=None,
    )
    await manager.start(req, client_id="answer")
    log.info("问答题已答并续跑：session=%s question=%s turn=%s", session.id, body.question_id, turn_id)
    return _sse(turn_id)


@router.get("/chat/active", summary="当前活跃 turn（诊断用）")
async def active_turns() -> dict[str, Any]:
    return {"turns": mgr.get_manager().active_turns()}


# ---------------------------------------------------------------------------
# 会话管理（F-B8）
# ---------------------------------------------------------------------------


@router.get("/chat/sessions", summary="会话列表（今天/昨天/更早/已归档）")
async def list_sessions(include_archived: bool = Query(default=True)) -> dict[str, Any]:
    sessions = store.list_sessions(include_archived=include_archived)
    return {
        "sessions": [s.model_dump(mode="json") for s in sessions],
        "groups": [
            {
                "key": g["key"],
                "label": g["label"],
                "items": [s.model_dump(mode="json") for s in g["items"]],
            }
            for g in store.group_sessions(sessions)
        ],
        "count": len(sessions),
    }


@router.post("/chat/sessions", summary="新建会话")
async def create_session(body: CreateSessionBody) -> dict[str, Any]:
    s = store.create_session(title=body.title, profile_id=body.profile_id)
    return {"session": s.model_dump(mode="json")}


@router.get("/chat/sessions/{session_id}/messages", summary="消息分页（倒序取，正序展示）")
async def list_messages(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    store.get_session(session_id)
    items = store.list_messages(session_id, limit=limit, offset=offset)
    return {
        "session_id": session_id,
        "items": [m.model_dump(mode="json") for m in items],
        "count": len(items),
        "total": store.message_count(session_id),
        "has_more": offset + len(items) < store.message_count(session_id),
        # 刷新页面后问答题卡片仍是「已确认」态（F-B7 跨刷新也成立）
        "questions": store.list_questions(session_id),
        "answered_questions": sorted(store.answered_questions(session_id)),
    }


@router.patch("/chat/sessions/{session_id}", summary="重命名 / 归档切换 / 换画像")
async def patch_session(session_id: str, body: PatchSessionBody) -> dict[str, Any]:
    s = store.update_session(
        session_id,
        title=body.title,
        archived=body.archived,
        profile_id=body.profile_id,
    )
    return {"session": s.model_dump(mode="json")}


@router.post("/chat/sessions/{session_id}/archive", summary="归档")
async def archive_session(session_id: str) -> dict[str, Any]:
    s = store.update_session(session_id, archived=True)
    return {"session": s.model_dump(mode="json"), "archived": True}


@router.post("/chat/sessions/{session_id}/unarchive", summary="取消归档")
async def unarchive_session(session_id: str) -> dict[str, Any]:
    s = store.update_session(session_id, archived=False)
    return {"session": s.model_dump(mode="json"), "archived": False}


@router.post("/chat/confirm-token", summary="申请破坏性操作的 confirm token")
async def confirm_token(body: ConfirmTokenBody) -> dict[str, Any]:
    return _issue_token(body.action, body.id)


@router.delete("/chat/sessions/{session_id}", summary="删会话及其全部内容（需 confirm）")
async def delete_session(session_id: str, confirm: str | None = Query(default=None)) -> dict[str, Any]:
    _require_token("delete-session", session_id, confirm)
    result = store.delete_session(session_id)
    log.info("会话已删除：%s", session_id)
    return result


# ---------------------------------------------------------------------------
# 素材上传（F-B2 / F-B3）
# ---------------------------------------------------------------------------


@router.post("/chat/upload", summary="上传素材（≤200MB + 类型白名单）")
async def chat_upload(
    session_id: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    project: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """落到 ``outputs/_uploads/<session_id>/<uuid><ext>``，并写 artifacts 索引。

    不合规返回 **400** 并说明原因（类型/大小/会话），不静默丢文件。
    """
    store.get_session(session_id)
    name = file.filename or "upload"
    mime = (file.content_type or "").lower()

    suffix = store.check_upload_type(name, mime)
    if suffix is None:
        raise UploadRejected(
            f"不支持的文件类型：{name}",
            detail={
                "name": name,
                "mime": mime or "(空)",
                "allowed_mime_prefixes": list(store.UPLOAD_MIME_PREFIXES),
                "allowed_suffixes": list(store.UPLOAD_SUFFIXES),
                "reason": "type_not_allowed",
            },
            hint="支持图片/视频/音频，或 .pdf .docx .md .txt .csv .xlsx",
        )

    target_dir = store.upload_dir(session_id)
    aid = store.new_id("a")
    dest = paths.resolve_inside(target_dir, f"{aid}{suffix}")

    size = 0
    try:
        with dest.open("wb") as f:
            while True:
                chunk = await file.read(UPLOAD_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > store.MAX_UPLOAD_BYTES:
                    raise UploadRejected(
                        f"文件超过 {store.MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限",
                        detail={"name": name, "size": size, "limit": store.MAX_UPLOAD_BYTES,
                                "reason": "too_large"},
                        hint="先压缩或裁剪后再传；单个文件上限 200MB",
                    )
                f.write(chunk)
    except UploadRejected:
        dest.unlink(missing_ok=True)  # 超限的半截文件不留
        raise
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise AtelierError(
            "素材落盘失败",
            detail={"name": name, "path": paths.rel_to_root(dest), "error": str(exc)},
            hint="检查磁盘空间与 outputs/_uploads 目录权限",
        ) from exc
    finally:
        await file.close()

    rel = paths.rel_to_root(dest)
    kind = store.kind_for(mime, suffix)
    record = store.record_artifact(
        session_id=session_id,
        turn_id=None,
        rel_path=rel,
        kind=kind,
        size=size,
        mime=mime or "application/octet-stream",
        project=project or store.UPLOAD_PROJECT,
        zone="素材",
        artifact_id=aid,
    )
    log.info("素材已上传：%s (%s, %d 字节)", rel, kind, size)
    # F-B3：返回结构化附件，**前端不会**把 name 拼进用户输入
    return {
        "id": record["id"],
        "kind": record["kind"],
        "name": name,
        "size": record["size"],
        "mime": record["mime"],
        "path": rel,
        "absolute_path": str(dest),
    }


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _validate_attachments(items: list[AttachmentIn]) -> list[models.Attachment]:
    """复核客户端回传的附件路径：必须在 ROOT 内且真实存在。

    不做这一步，前端就能把 ``/etc/passwd`` 之类的路径塞进 agent 上下文
    （F-B3 说附件带真实路径，那就必须保证这个路径是工作台自己的）。
    """
    out: list[models.Attachment] = []
    for a in items:
        p = paths.resolve_inside(paths.ROOT, a.path)
        if not p.is_file():
            raise UploadRejected(
                "附件不存在或已被移走",
                detail={"path": a.path, "reason": "not_found"},
                hint="重新拖入/粘贴一次，或先在内容库里确认文件还在",
            )
        rel = paths.rel_to_root(p)
        out.append(
            models.Attachment(
                id=a.id or store.new_id("a"),
                kind=a.kind or store.kind_for(a.mime, p.suffix),
                path=rel,
                name=a.name or p.name,
                size=a.size or p.stat().st_size,
                mime=a.mime or "application/octet-stream",
            )
        )
    return out


def _autotitle(session: models.Session, text: str, attachments: list[models.Attachment]) -> None:
    """首条消息定标题（SPEC-03 §5：取前 20 字）。**只用文字，绝不用文件名。**"""
    if session.title != store.DEFAULT_TITLE or not text:
        return
    store.update_session(session.id, title=store.title_from_text(text), touch=False)
