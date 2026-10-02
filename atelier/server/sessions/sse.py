"""SPEC-03 §2 · SSE 事件序列化。

**标准 ``text/event-stream``**：每个 :class:`TurnEvent` 一帧 ``data: {json}\\n\\n``。

刻意**不做**「tail 文件 + 轮询」——那是参考实现里被验证过的技术债（PRD 14.2 点名）：
本域的事件由 :meth:`TurnManager.events` 从内存队列实时推到 SSE 响应，
落盘只在「重连后补齐」时读一次。

两帧之间的静默用 ``: keep-alive`` 注释帧兜底（避免代理/浏览器把空闲连接掐掉），
注释帧对前端不可见。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse
from starlette.responses import Response

from ..harness.base import TurnEvent

__all__ = [
    "KEEPALIVE_SECONDS",
    "SSE_HEADERS",
    "format_comment",
    "format_event",
    "format_events",
    "sse_response",
]

#: 多久没有事件就发一帧注释保活
KEEPALIVE_SECONDS = 15.0

#: 关掉一切可能造成缓冲的东西（nginx 缓冲会毁掉打字机）
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-store, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def format_event(ev: TurnEvent | dict[str, Any]) -> str:
    """一个事件 → 一帧 SSE。

    ``json.dumps`` 会把换行转义成 ``\\n``，所以单行 ``data:`` 就是完整一帧，
    不需要多行 ``data:`` 拼接。
    """
    payload = ev.to_dict() if isinstance(ev, TurnEvent) else dict(ev)
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def format_comment(text: str) -> str:
    """注释帧（保活 / 连通性确认），前端 EventSource 会忽略。"""
    return f": {text}\n\n"


def format_events(events: list[TurnEvent]) -> str:
    """批量重放（backlog）用，一帧一个事件。"""
    return "".join(format_event(e) for e in events)


def sse_response(
    source: AsyncIterator[TurnEvent] | AsyncIterator[str],
    *,
    headers: dict[str, str] | None = None,
) -> StreamingResponse:
    """把事件流包成 ``text/event-stream`` 响应。

    ``source`` 既可以吐 :class:`TurnEvent`（自动序列化），也可以直接吐已格式化好的
    字符串（用于手动发注释保活帧）。客户端断开时生成器被关闭，**不会**连带取消
    那一轮生成——这是「断线不丢」的前提：轮次继续跑，重连后从落盘补齐。
    """
    merged = {**SSE_HEADERS, **(headers or {})}

    async def _gen() -> AsyncIterator[str]:
        yield format_comment("atelier chat stream")
        async for item in source:
            yield item if isinstance(item, str) else format_event(item)
        yield format_comment("atelier chat stream end")

    resp: Response = StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers=merged,
    )
    return resp  # type: ignore[return-value]
