"""SPEC-01 §3 · Harness 抽象（**本文件不得出现 SDK 的 import 名**，验收会 grep）。

业务层只认这里的类型。provider 差异（流式怎么拿、中断怎么停、SDK 消息怎么映射）
全部封在 :mod:`atelier.server.harness.claude_sdk` 里；换 provider 只加一个实现文件。
那个包（PyPI 名 ``claude-agent-sdk``）只允许出现在 claude_sdk.py 内部。

本文件同时提供两个不依赖任何 provider 的东西：

1. :class:`TurnRecorder` —— 每轮事件写 ``var/sessions/<sid>/<turn_id>.jsonl``
   （SPEC-01 §3 硬性要求），``resume`` 从这里读。真实 harness 和 Mock 共用，
   保证「断线恢复」这条链路在两种 provider 下行为完全一致。
2. :class:`MockHarness` —— 写死的流式实现，``ATELIER_MOCK=1`` 启用。
   没有 API key 也能跑通全部测试与 E2E 冒烟，这是 SPEC-00 §3「M0 出口标准」
   能自动化验收的前提。

关于结构化产出（设计意图，供未来实现参考）：SDK 的 ``ClaudeAgentOptions.output_format``
可以让模型直接返回结构化 JSON，比解析 Markdown 可靠得多。规划：

- ``EventType.QUESTION``（反问 → 前端渲染选项卡片，PRD F-B7）：走 ``output_format``
- ``EventType.GATE_RESULT``：由 :func:`atelier.gates.registry.run_gates` 本地算，不信任模型自报
- 普通正文：走流式文本（打字机效果，PRD F-B4）

两者会混在同一个 turn 里，所以 :class:`EventType` 同时承载「增量文本」和「结构化块」。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from .. import paths
from ..core import models
from ..errors import SessionBusy

__all__ = [
    "EventType",
    "Harness",
    "HealthReport",
    "MockHarness",
    "TurnEvent",
    "TurnRecorder",
    "TurnRequest",
]


class EventType(str, Enum):
    """一轮生成过程中推送的事件类型（值即 SSE 里的 ``type``，§11 冻结）。"""

    THINKING_START = "thinking_start"
    THINKING_DELTA = "thinking_delta"  # 独立思考流（PRD F-B1）
    TEXT_DELTA = "text_delta"  # 正文流
    TOOL_CALL = "tool_call"  # 工具调用（含门禁调用，前端要显示）
    TOOL_RESULT = "tool_result"
    QUESTION = "question"  # 反问 → 前端渲染选项卡片（F-B7）
    ARTIFACT = "artifact"  # 产物落盘完成
    GATE_RESULT = "gate_result"  # 门禁结果块
    DONE = "done"
    ERROR = "error"


@dataclass
class TurnEvent:
    """一轮生成中的一个事件。字段名在 §11 冻结。"""

    type: EventType
    turn_id: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """SSE / jsonl 的统一形状：``{"type","turn_id","data"}``。"""
        return {"type": self.type.value, "turn_id": self.turn_id, "data": self.data}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TurnEvent:
        return cls(type=EventType(raw["type"]), turn_id=str(raw["turn_id"]), data=raw.get("data") or {})

    def text(self) -> str:
        """便捷取 ``data["text"]``（THINKING_DELTA / TEXT_DELTA 都用它）。"""
        return str(self.data.get("text") or "")


@dataclass
class TurnRequest:
    """一轮生成的输入。``profile`` 由调用方内联（并发画像不互相污染，PRD 4.2）。"""

    session_id: str
    turn_id: str
    prompt: str
    profile: models.Profile | None
    attachments: list[models.Attachment] = field(default_factory=list)
    system_suffix: str | None = None  # 每轮重申「先查技能库」，对抗指令衰减（PRD 4.2）
    project: str | None = None

    def attachments_block(self) -> str:
        """附件的文本化描述（拼进 prompt；真实 harness 还要把文件交给 SDK）。"""
        if not self.attachments:
            return ""
        lines = [f"- [{a.kind}] {a.name}（{a.mime}, {a.size} 字节, {a.path}）" for a in self.attachments]
        return "用户本轮附了这些素材：\n" + "\n".join(lines)


@dataclass
class HealthReport:
    """provider 健康状况（doctor 与 ``/api/health`` 用）。"""

    name: str
    ok: bool
    detail: dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail, "message": self.message}


@runtime_checkable
class Harness(Protocol):
    """AI 运行时抽象（SPEC-01 §3 冻结方法名）。"""

    name: str

    def stream(self, req: TurnRequest) -> AsyncIterator[TurnEvent]:
        """产生本轮全部事件。实现必须是异步生成器。"""
        ...

    async def interrupt(self, turn_id: str) -> None:
        """必须在 2s 内让生成停止（PRD F-B5 验收标准）。"""
        ...

    async def resume(self, turn_id: str) -> list[TurnEvent]:
        """断线恢复：返回该轮已产生的全部事件（PRD F-B6）。"""
        ...

    async def health(self) -> HealthReport: ...

    async def aclose(self) -> None: ...


# ---------------------------------------------------------------------------
# 每轮事件落盘（PRD 13「每轮对话落盘」）
# ---------------------------------------------------------------------------


class TurnRecorder:
    """把一轮事件追加写进 ``var/sessions/<sid>/<turn_id>.jsonl``。"""

    def __init__(self, session_id: str, turn_id: str) -> None:
        self.session_id = session_id
        self.turn_id = turn_id
        self.path = paths.turn_log(session_id, turn_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, ev: TurnEvent) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")

    def read_all(self) -> list[TurnEvent]:
        if not self.path.exists():
            return []
        out: list[TurnEvent] = []
        for line in self.path.read_text("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(TurnEvent.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, ValueError):
                # 落盘可能正在被写到最后一行；坏行跳过但不让恢复整条链路挂掉
                continue
        return out


def read_turn_events(turn_id: str) -> list[TurnEvent]:
    """按 turn_id 反查落盘事件（``resume`` 只拿得到 turn_id 时的入口）。"""
    events: list[TurnEvent] = []
    for p in paths.turn_log_paths(turn_id):
        for line in p.read_text("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(TurnEvent.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return events


# ---------------------------------------------------------------------------
# MockHarness（ATELIER_MOCK=1）
# ---------------------------------------------------------------------------

#: 写死的分片，保证流式行为可测（可被 delay/chunks 覆写）
MOCK_CHUNKS: tuple[str, ...] = (
    "收到，",
    "先按你的定位理了一下这版：\n\n",
    "1. 开头直接给结论，不铺垫；\n2. 中间用一个具体数字撑住；\n",
    "3. 结尾留一个真问题。\n\n",
    "要我把它落成成品文件吗？",
)

MOCK_THINKING: tuple[str, ...] = ("先查技能库有没有现成的", "再决定是写正文还是先跑技能")


class MockHarness:
    """不依赖 API key 的流式实现，行为与真实 harness 对齐。

    对齐点：同样的事件序列、每轮落 jsonl、同一 session 只允许一个活跃 turn、
    ``interrupt`` 在 2s 内生效、``resume`` 从落盘重建。唯一区别是内容写死。
    """

    name = "mock"

    def __init__(
        self,
        *,
        delay: float = 0.02,
        chunks: tuple[str, ...] = MOCK_CHUNKS,
        thinking: tuple[str, ...] = MOCK_THINKING,
    ) -> None:
        self.delay = delay
        self.chunks = chunks
        self.thinking = thinking
        self._active: dict[str, str] = {}  # session_id → turn_id（PRD F-B12）
        self._stop: dict[str, asyncio.Event] = {}
        self._finished: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._events: dict[str, list[TurnEvent]] = {}  # turn_id → 已产生事件
        self._lock = asyncio.Lock()
        self._closed = False

    # -- 内部 ---------------------------------------------------------------

    def _chunks_for(self, req: TurnRequest) -> tuple[str, ...]:
        """分片序列，首片带上画像名——肉眼可确认画像确实注入了这一轮。"""
        who = req.profile.name if req.profile else "通用模式（未注入画像）"
        return (f"以「{who}」的视角：", *self.chunks)

    async def _pause(self, turn_id: str) -> bool:
        """等一小会儿；返回 False 表示已被中断/取消。"""
        stop = self._stop.get(turn_id)
        if stop is not None and stop.is_set():
            return False
        if self.delay:
            try:
                await asyncio.wait_for(self._sleep(turn_id), timeout=self.delay * 4)
            except TimeoutError:
                return False
            except asyncio.CancelledError:
                return False
        return not (stop is not None and stop.is_set())

    async def _sleep(self, turn_id: str) -> None:
        await asyncio.sleep(self.delay)
        if self._stop.get(turn_id) is not None and self._stop[turn_id].is_set():
            raise TimeoutError

    # -- Harness 协议 -------------------------------------------------------

    async def stream(self, req: TurnRequest) -> AsyncIterator[TurnEvent]:
        """流式产出本轮事件（异步生成器）。"""
        async with self._lock:
            running = self._active.get(req.session_id)
            if running is not None and running != req.turn_id:
                raise SessionBusy(
                    "该会话正在被另一个窗口生成",
                    detail={"session_id": req.session_id, "running_turn_id": running},
                )
            self._active[req.session_id] = req.turn_id
        self._stop[req.turn_id] = asyncio.Event()
        self._finished[req.turn_id] = asyncio.Event()
        self._events[req.turn_id] = []
        self._tasks[req.turn_id] = asyncio.current_task()
        recorder = TurnRecorder(req.session_id, req.turn_id)
        acc: list[str] = []

        def emit(ev: TurnEvent) -> TurnEvent:
            """先落盘再返回。断线也不丢已生成内容（PRD F-B6）。同步实现，
            这样取消路径（``except asyncio.CancelledError``）里也能安全留痕。"""
            self._events.setdefault(req.turn_id, []).append(ev)
            try:
                recorder.write(ev)
            except OSError:
                # 落盘失败不能把生成也拖垮；doctor 第 13 项会暴露这个故障
                pass
            return ev

        try:
            yield emit(
                TurnEvent(EventType.THINKING_START, req.turn_id, {"phase": "start"})
            )
            for t in self.thinking:
                if not await self._pause(req.turn_id):
                    break
                yield emit(TurnEvent(EventType.THINKING_DELTA, req.turn_id, {"text": t}))
            # 思考流结束：冻结的 EventType 里没有 THINKING_END，用 delta 收尾
            yield emit(
                TurnEvent(EventType.THINKING_DELTA, req.turn_id, {"text": "", "phase": "end"})
            )

            if self._stop[req.turn_id].is_set():
                yield emit(
                    TurnEvent(
                        EventType.DONE, req.turn_id, {"interrupted": True, "text": "".join(acc)}
                    )
                )
                return

            for chunk in self._chunks_for(req):
                if not await self._pause(req.turn_id):
                    break
                acc.append(chunk)
                yield emit(TurnEvent(EventType.TEXT_DELTA, req.turn_id, {"text": chunk}))

            interrupted = self._stop[req.turn_id].is_set()
            yield emit(
                TurnEvent(
                    EventType.DONE,
                    req.turn_id,
                    {
                        "text": "".join(acc),
                        "interrupted": interrupted,
                        "provider": self.name,
                    },
                )
            )
        except asyncio.CancelledError:
            # 任务被硬取消：尽力留一条 DONE 痕迹（PRD 原则四：不静默）
            try:
                emit(
                    TurnEvent(
                        EventType.DONE,
                        req.turn_id,
                        {"interrupted": True, "text": "".join(acc), "cancelled": True},
                    )
                )
            except Exception:  # noqa: BLE001,S110 - 取消路径不再抛
                pass
            raise
        finally:
            if self._active.get(req.session_id) == req.turn_id:
                self._active.pop(req.session_id, None)
            done = self._finished.get(req.turn_id)
            if done is not None:
                done.set()

    async def interrupt(self, turn_id: str) -> None:
        """置停止标记；0.5s 内没自然退出再硬 cancel（SPEC-01 §3 规定的顺序）。"""
        stop = self._stop.get(turn_id)
        if stop is None:
            return
        stop.set()
        finished = self._finished.get(turn_id)
        if finished is not None and not finished.is_set():
            try:
                await asyncio.wait_for(asyncio.shield(finished.wait()), timeout=0.5)
            except TimeoutError:
                task = self._tasks.get(turn_id)
                if task is not None and not task.done():
                    task.cancel()

    async def resume(self, turn_id: str) -> list[TurnEvent]:
        """从内存索引或 jsonl 重建该轮全部事件。"""
        cached = self._events.get(turn_id)
        if cached:
            return list(cached)
        return read_turn_events(turn_id)

    async def health(self) -> HealthReport:
        return HealthReport(
            name=self.name,
            ok=True,
            detail={
                "provider": self.name,
                "mock": True,
                "delay": self.delay,
                "active_sessions": len(self._active),
            },
            message="Mock harness 就绪（ATELIER_MOCK=1，不需要 API key）",
        )

    async def aclose(self) -> None:
        """只置停止标记，**不** cancel 任务。

        ``_tasks`` 记的是消费方的 task（生成器内 ``current_task()`` 拿到的就是它），
        在这里 cancel 会连带杀掉 SSE 请求处理器。硬取消只属于 :meth:`interrupt`。
        """
        self._closed = True
        for stop in self._stop.values():
            stop.set()
        self._active.clear()
