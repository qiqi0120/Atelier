"""SPEC-03 · 对话工作台域（会话 / 消息 / 每轮事件 / 活跃 turn 管理）。

分层：

- :mod:`.store`    会话 + 消息 + 产物索引的 CRUD（SQLite），不涉及流式
- :mod:`.manager`  ★ 活跃 turn 管理、并发锁、中断、断线恢复（SPEC-03 §3）
- :mod:`.sse`      SSE 事件序列化（SPEC-03 §2 要求的标准 ``text/event-stream``）

``api/chat.py`` 只做参数校验与路由，三层都不 import 任何 provider 实现，
统一通过 ``harness.registry.get_harness()`` 取当前 harness。
"""

from __future__ import annotations

from .manager import TurnManager, TurnState, get_manager, reset_manager
from .sse import KEEPALIVE_SECONDS, format_comment, format_event, sse_response
from .store import (
    DEFAULT_UPLOAD_DIR_NAME,
    MAX_UPLOAD_BYTES,
    UPLOAD_MIME_PREFIXES,
    UPLOAD_SUFFIXES,
    add_message,
    answered_questions,
    create_session,
    delete_session,
    get_session,
    group_sessions,
    list_messages,
    list_sessions,
    mark_answered,
    new_id,
    record_artifact,
    update_session,
    upload_dir,
)

__all__ = [
    "DEFAULT_UPLOAD_DIR_NAME",
    "KEEPALIVE_SECONDS",
    "MAX_UPLOAD_BYTES",
    "UPLOAD_MIME_PREFIXES",
    "UPLOAD_SUFFIXES",
    "TurnManager",
    "TurnState",
    "add_message",
    "answered_questions",
    "create_session",
    "delete_session",
    "format_comment",
    "format_event",
    "get_manager",
    "get_session",
    "group_sessions",
    "list_messages",
    "list_sessions",
    "mark_answered",
    "new_id",
    "record_artifact",
    "reset_manager",
    "sse_response",
    "update_session",
    "upload_dir",
]
