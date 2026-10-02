"""SPEC-01 §4 · ``ClaudeSDKHarness`` —— **全项目唯一 import ``claude_agent_sdk`` 的文件**。

本文件已在 venv 内用 ``dir()`` / ``inspect.signature()`` 对 **claude-agent-sdk 0.2.163**
实测确认（与 SPEC-01 §4 的描述一致，两处补充/修正见下）：

- 入口齐全：``query`` / ``ClaudeSDKClient`` / ``ClaudeAgentOptions`` / ``AssistantMessage`` /
  ``TextBlock`` / ``ThinkingBlock`` / ``ResultMessage`` / ``SystemMessage`` / ``UserMessage`` /
  ``ToolUseBlock`` / ``ToolResultBlock`` / ``StreamEvent`` / ``tool`` / ``create_sdk_mcp_server``
  都能从顶层 ``claude_agent_sdk`` 直接 import（``StreamEvent`` 也在顶层，不必进 ``.types``）
- ``tool(name, description, input_schema, annotations=None)``；``input_schema`` 收 ``type | dict``
- ``create_sdk_mcp_server(name, version="1.0.0", tools=None)``
- ``ClaudeSDKClient.interrupt()`` 是**同步**方法（返回 None，不是协程）——中断路径按同步调
- ``Query`` 签名是 keyword-only：``query(*, prompt, options=None, transport=None)``

两处 spec 未写、需要实现时注意的实测事实：

1. ``ThinkingBlock(thinking: str, signature: str)`` —— ``signature`` 是**必填**位置参数。
2. ``StreamEvent`` 的字段是 ``uuid / session_id / event / parent_tool_use_id``；
   ``event`` 是普通 ``dict``，取增量即 ``event["delta"]["text"]``。

PRD F-B1「独立思考过程流」走 SDK 原生能力，不自己模拟：``thinking=ThinkingConfigAdaptive``
+ ``max_thinking_tokens`` → ``AssistantMessage.content`` 里出现 :class:`ThinkingBlock` → 映射成
``THINKING_DELTA``。``include_partial_messages=True`` 只用来拿正文 token 级增量。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from claude_agent_sdk import (  # noqa: F401 - 供下游 isinstance 判断与类型标注
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
    tool,
)

from .. import paths
from ..config import get_settings
from ..core import models
from ..errors import HarnessAuthError, HarnessError, HarnessTimeout, SessionBusy
from .base import EventType, HealthReport, TurnEvent, TurnRecorder, read_turn_events
from .tools import allowed_tool_names, build_mcp_server

__all__ = [
    "SYSTEM_PROMPT_BASE",
    "ClaudeSDKHarness",
    "build_system_prompt",
    "events_from_message",
    "system_prompt_for",
]

#: 基础系统提示。画像由调用方内联追加（PRD 4.2：不落全局文件，避免并发画像互相污染）。
#: SPEC-02 §4 拥有最终措辞；这里给的是能跑起来的基线。
SYSTEM_PROMPT_BASE = """你是 Atelier 的创作助手，服务于一位社交媒体创作者。

工作方式：
1. 先查技能库：动手前先看有没有现成技能能直接用（能力地图 / 技能库），不要从零重造。
2. 产出必须过门禁：正文定稿后必须调用 `atelier_gate_run` 自查，返回 blocked=true 就必须先改。
3. 落盘必须走 `atelier_artifact_write`，它内部会再判一次门禁；被拒是正常的，按 fix_hint 改。
4. 门禁结果以工具返回为准，不要自己宣布「已通过」。

风格：像真人说话。不用「在当今」「随着…的发展」这类铺垫，不写总结句，不堆形容词。
不确定就反问，不要编造数据、案例或用户经历。"""

#: 每轮重申的任务锚（对抗指令衰减，PRD 4.2）
SYSTEM_SUFFIX_DEFAULT = "【本轮提醒】先查技能库，再产出；产出前跑 atelier_gate_run；被拒就改到通过。"


def system_prompt_for(profile: models.Profile | None, system_suffix: str | None = None) -> str:
    """把画像内联进系统提示。``general_mode=True`` 时不注入画像（PRD 4.2）。"""
    parts = [SYSTEM_PROMPT_BASE]
    if profile is not None and not profile.general_mode:
        from ..core.models import DIMENSION_LABELS  # 局部 import：避免模块级循环

        lines = ["创作者画像（切画像后风格要跟着变）：", f"- 画像名：{profile.name}",
                 f"- 目标平台：{'、'.join(profile.platforms) or '未指定'}"]
        for dim, text in (
            ("identity", profile.identity),
            ("style", profile.style),
            ("audience", profile.audience),
            ("platform_rules", profile.platform_rules),
            ("preferences", profile.preferences),
        ):
            if text.strip():
                lines.append(f"- {DIMENSION_LABELS[dim]}：{text.strip()}")
        adopted = [m for m in profile.memories if m.adopted]
        if adopted:
            lines.append("- 长期记忆：")
            lines.extend(f"  · {m.text}（{m.source}）" for m in adopted)
        parts.append("\n".join(lines))
    parts.append(system_suffix or SYSTEM_SUFFIX_DEFAULT)
    return "\n\n".join(parts)


def build_system_prompt(req: Any) -> str:
    """从 :class:`TurnRequest` 组系统提示。"""
    return system_prompt_for(getattr(req, "profile", None), getattr(req, "system_suffix", None))


# ---------------------------------------------------------------------------
# SDK 消息 → TurnEvent
# ---------------------------------------------------------------------------


def _stream_text_delta(msg: StreamEvent) -> str | None:
    """从 ``StreamEvent`` 里取正文增量；不是正文增量返回 None。"""
    ev = getattr(msg, "event", None)
    if not isinstance(ev, dict) or ev.get("type") != "content_block_delta":
        return None
    delta = ev.get("delta")
    if not isinstance(delta, dict):
        return None
    if delta.get("type") == "text_delta":
        return str(delta.get("text") or "")
    if delta.get("type") == "thinking_delta":
        return str(delta.get("thinking") or "")
    return None


def events_from_message(msg: Any, turn_id: str) -> list[TurnEvent]:
    """把一条 SDK 消息映射成 0..n 个 :class:`TurnEvent`（纯函数，好测）。

    映射表：

    ==========================  ==============================================
    ``StreamEvent``            ``content_block_delta`` → 正文/思考 token 增量
    ``AssistantMessage``       ``ThinkingBlock``→THINKING_DELTA，``TextBlock``→TEXT_DELTA，
                               ``ToolUseBlock``→TOOL_CALL，``ToolResultBlock``→TOOL_RESULT
    ``ResultMessage``          DONE（``is_error`` → ERROR，带失败原因）
    ``SystemMessage``          忽略（init 之类是 SDK 内部握手信号）
    ==========================  ==============================================
    """
    out: list[TurnEvent] = []

    if isinstance(msg, StreamEvent):
        text = _stream_text_delta(msg)
        if text:
            kind = "thinking_delta" if (msg.event or {}).get("delta", {}).get("type") == "thinking_delta" else "text_delta"
            out.append(
                TurnEvent(
                    EventType.THINKING_DELTA if kind == "thinking_delta" else EventType.TEXT_DELTA,
                    turn_id,
                    {"text": text},
                )
            )
        return out

    if isinstance(msg, AssistantMessage):
        for block in msg.content or []:
            if isinstance(block, ThinkingBlock):
                out.append(TurnEvent(EventType.THINKING_DELTA, turn_id, {"text": block.thinking}))
            elif isinstance(block, TextBlock):
                out.append(TurnEvent(EventType.TEXT_DELTA, turn_id, {"text": block.text}))
            elif isinstance(block, ToolUseBlock):
                out.append(
                    TurnEvent(
                        EventType.TOOL_CALL,
                        turn_id,
                        {"id": block.id, "name": block.name, "input": block.input},
                    )
                )
            elif isinstance(block, ToolResultBlock):
                out.append(
                    TurnEvent(
                        EventType.TOOL_RESULT,
                        turn_id,
                        {
                            "tool_use_id": block.tool_use_id,
                            "content": _plain(block.content),
                            "is_error": bool(getattr(block, "is_error", False)),
                        },
                    )
                )
        if getattr(msg, "error", None):
            out.append(TurnEvent(EventType.ERROR, turn_id, {"message": str(msg.error)}))
        return out

    if isinstance(msg, ResultMessage):
        if msg.is_error:
            out.append(
                TurnEvent(
                    EventType.ERROR,
                    turn_id,
                    {
                        "message": msg.result or f"harness 返回错误（{msg.subtype}）",
                        "subtype": msg.subtype,
                        "api_error_status": getattr(msg, "api_error_status", None),
                    },
                )
            )
        out.append(
            TurnEvent(
                EventType.DONE,
                turn_id,
                {
                    "text": msg.result or "",
                    "subtype": msg.subtype,
                    "cost_usd": msg.total_cost_usd,
                    "num_turns": msg.num_turns,
                    "duration_ms": msg.duration_ms,
                    "is_error": bool(msg.is_error),
                },
            )
        )
        return out

    if isinstance(msg, (UserMessage, SystemMessage)):
        return out
    return out


def _plain(content: Any) -> Any:
    """把工具返回的 content 压成可 JSON 化形状（SDK 可能给对象或 list）。"""
    if content is None or isinstance(content, (str, int, float, bool)):
        return content
    if isinstance(content, list):
        return [_plain(c) for c in content]
    for attr in ("text", "content", "data"):
        if hasattr(content, attr):
            return _plain(getattr(content, attr))
    return str(content)


# ---------------------------------------------------------------------------
# Harness 实现
# ---------------------------------------------------------------------------


class ClaudeSDKHarness:
    """基于 ``ClaudeSDKClient`` 的有状态多轮 harness。

    关键取舍：

    - **有状态**：``session_id`` → 一个常驻 :class:`ClaudeSDKClient`，多轮共享上下文
      （PRD F-B1「对话工作台」要求记住上文）。``continue_conversation`` 打开。
    - **超时**：整轮包在 :func:`asyncio.wait_for` 里，超 ``harness_timeout``（默认 120s）
      抛 ``HarnessTimeout``（504，SPEC-01 §8）。
    - **中断**：先置停止标记 + ``client.interrupt()``（SDK 侧兜底），再 ``task.cancel()``。
    - **扩展点**：``extra_options`` 直接透传给 ``ClaudeAgentOptions``，给后续批次挂
      原生 ``skills=[...]`` / ``output_format={...}`` 用（**本文件不实现技能加载**，
      那是 W1-B 的 ``atelier/server/skills/`` 与 ``atelier/skills/`` 的职责）。
    """

    name = "claude_sdk"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.anthropic_api_key
        self._model = model or settings.anthropic_model
        self._timeout = float(timeout if timeout is not None else settings.harness_timeout)
        self._extra_options = dict(extra_options or {})
        self._clients: dict[str, ClaudeSDKClient] = {}
        self._connected: set[str] = set()
        self._sdk_sessions: dict[str, str] = {}  # atelier session_id → SDK session_id
        self._active: dict[str, str] = {}  # session_id → turn_id
        self._stop: dict[str, asyncio.Event] = {}
        self._finished: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._events: dict[str, list[TurnEvent]] = {}
        self._lock = asyncio.Lock()

    # -- 选项 ---------------------------------------------------------------

    def build_options(self, req: Any, resume: str | None = None) -> ClaudeAgentOptions:
        """构造本轮 :class:`ClaudeAgentOptions`。

        ``resume`` 是上一轮 :class:`ResultMessage` 回传的 SDK session_id——**有状态多轮
        就靠它**（SDK 的 ``continue_conversation`` 续最近一次会话，``resume`` 续指定会话）。
        客户端每轮新建而不是常驻，因为画像是**按轮内联**进 ``system_prompt`` 的
        （PRD 4.2：切画像后下一轮风格立刻变，常驻 client 换不了 system_prompt）。

        ``extra_options`` 在最后合并，可以覆盖任意默认字段——上层要挂
        ``skills`` / ``output_format`` / ``agents`` 时用，不必改本文件。
        """
        if not self._api_key:
            raise HarnessAuthError(
                "ANTHROPIC_API_KEY 未配置或无效",
                detail={"env": "ANTHROPIC_API_KEY"},
                hint="到「设置」页填入 ANTHROPIC_API_KEY（只写不回传），或用 ATELIER_MOCK=1 先跑通流程",
            )

        options: dict[str, Any] = {
            "system_prompt": build_system_prompt(req),
            "cwd": str(paths.ROOT),
            "include_partial_messages": True,  # 正文 token 级增量
            "permission_mode": "acceptEdits",
            "allowed_tools": allowed_tool_names(),
            "mcp_servers": {self._mcp_name(): build_mcp_server()},
            "env": {"ANTHROPIC_API_KEY": self._api_key},
        }
        if resume:
            options["resume"] = resume
            options["continue_conversation"] = True
        if self._model:
            options["model"] = self._model
        # PRD F-B1：思考流用原生能力（ThinkingConfigAdaptive），不是自己模拟
        with contextlib.suppress(TypeError, ValueError, ImportError):
            from claude_agent_sdk import ThinkingConfigAdaptive  # 局部 import：新版本才有

            options["thinking"] = ThinkingConfigAdaptive()
            options["max_thinking_tokens"] = 4096
        options.update(self._extra_options)
        return ClaudeAgentOptions(**options)

    @staticmethod
    def _mcp_name() -> str:
        from .tools import MCP_SERVER_NAME

        return MCP_SERVER_NAME

    @asynccontextmanager
    async def _turn_client(self, req: Any) -> AsyncIterator[ClaudeSDKClient]:
        """本轮的 SDK 客户端（用完即关；上下文靠 ``resume`` 延续）。"""
        client = ClaudeSDKClient(self.build_options(req, resume=self._sdk_sessions.get(req.session_id)))
        await client.connect()
        self._clients[req.session_id] = client
        self._connected.add(req.session_id)
        try:
            yield client
        finally:
            with contextlib.suppress(Exception):
                await client.disconnect()
            self._clients.pop(req.session_id, None)
            self._connected.discard(req.session_id)

    def _remember_session(self, session_id: str, sdk_session_id: str | None) -> None:
        """记住 SDK 侧 session_id，下一轮用 ``resume`` 接上。"""
        if sdk_session_id:
            self._sdk_sessions[session_id] = sdk_session_id

    # -- Harness 协议 -------------------------------------------------------

    async def stream(self, req: Any) -> AsyncIterator[TurnEvent]:
        """本轮全部事件（异步生成器）。"""
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
        thinking_open = False

        def emit(ev: TurnEvent) -> TurnEvent:
            self._events.setdefault(req.turn_id, []).append(ev)
            with contextlib.suppress(OSError):
                recorder.write(ev)
            return ev

        try:
            prompt = req.prompt + ("\n" + req.attachments_block() if req.attachments else "")
            stop = self._stop[req.turn_id]
            async with self._turn_client(req) as client:
                await client.query(prompt, session_id=req.session_id)
                try:
                    async for msg in asyncio.wait_for(
                        _drain(client.receive_response(), stop), timeout=self._timeout
                    ):
                        self._remember_session(req.session_id, getattr(msg, "session_id", None))
                        evs = events_from_message(msg, req.turn_id)
                        for ev in evs:
                            if ev.type == EventType.THINKING_DELTA and not thinking_open:
                                thinking_open = True
                                yield emit(
                                    TurnEvent(EventType.THINKING_START, req.turn_id, {"phase": "start"})
                                )
                            if stop.is_set() and ev.type in (EventType.TEXT_DELTA, EventType.THINKING_DELTA):
                                continue  # 已中断：不再吐增量
                            yield emit(ev)
                        if evs and evs[-1].type in (EventType.DONE, EventType.ERROR) and stop.is_set():
                            break
                except TimeoutError:
                    # PRD 13：AI 生成 > 120s → 504，不是 500 空壳
                    yield emit(
                        TurnEvent(
                            EventType.ERROR,
                            req.turn_id,
                            {
                                "code": "HarnessTimeout",
                                "message": f"AI 生成超时（>{self._timeout:.0f}s）",
                                "hint": "把需求拆小一点再试；已生成内容在会话里不会丢",
                            },
                        )
                    )
                    raise HarnessTimeout(
                        f"AI 生成超时（>{self._timeout:.0f}s）",
                        detail={
                            "session_id": req.session_id,
                            "turn_id": req.turn_id,
                            "timeout_s": self._timeout,
                        },
                        hint="把需求拆小一点再试；已生成内容在会话里不会丢",
                    ) from None
                except (HarnessAuthError, SessionBusy, HarnessTimeout):
                    raise
                except Exception as exc:
                    # 失败要留痕：先推 ERROR 事件（前端能显示），再抛带原因的错误
                    yield emit(
                        TurnEvent(
                            EventType.ERROR,
                            req.turn_id,
                            {
                                "code": "HarnessError",
                                "message": f"{type(exc).__name__}: {exc}",
                                "type": type(exc).__name__,
                            },
                        )
                    )
                    raise HarnessError(
                        "AI 运行时连接失败",
                        detail={"type": type(exc).__name__, "error": str(exc)[:2000]},
                        hint="跑 `atelier doctor` 看环境诊断；已生成部分不会丢",
                    ) from exc
            if thinking_open:
                # 冻结的 EventType 没有 THINKING_END，用空 delta 收尾
                yield emit(TurnEvent(EventType.THINKING_DELTA, req.turn_id, {"text": "", "phase": "end"}))
        finally:
            if self._active.get(req.session_id) == req.turn_id:
                self._active.pop(req.session_id, None)
            done = self._finished.get(req.turn_id)
            if done is not None:
                done.set()

    async def interrupt(self, turn_id: str) -> None:
        """停止标记 + SDK ``interrupt()`` 兜底，再不行才 cancel（SPEC-01 §3 的顺序）。"""
        stop = self._stop.get(turn_id)
        if stop is None:
            return
        stop.set()
        for session_id, tid in list(self._active.items()):
            if tid != turn_id:
                continue
            client = self._clients.get(session_id)
            if client is not None:
                with contextlib.suppress(Exception):
                    client.interrupt()  # 0.2.163 实测：同步方法
            break
        finished = self._finished.get(turn_id)
        if finished is not None and not finished.is_set():
            try:
                await asyncio.wait_for(asyncio.shield(finished.wait()), timeout=0.5)
            except TimeoutError:
                task = self._tasks.get(turn_id)
                if task is not None and not task.done():
                    task.cancel()

    async def resume(self, turn_id: str) -> list[TurnEvent]:
        cached = self._events.get(turn_id)
        if cached:
            return list(cached)
        return read_turn_events(turn_id)

    async def health(self) -> HealthReport:
        return HealthReport(
            name=self.name,
            ok=bool(self._api_key),
            detail={
                "provider": self.name,
                "sdk": "claude-agent-sdk",
                "api_key": "已配置" if self._api_key else "未配置",
                "model": self._model or "(SDK 默认)",
                "timeout_s": self._timeout,
                "sessions": len(self._clients),
                "mcp_tools": len(allowed_tool_names()),
                "extra_options": sorted(self._extra_options),
            },
            message="harness 就绪" if self._api_key else "缺 ANTHROPIC_API_KEY（用 ATELIER_MOCK=1 可先跑通）",
        )

    async def aclose(self) -> None:
        for stop in self._stop.values():
            stop.set()
        for client in self._clients.values():
            with contextlib.suppress(Exception):
                await client.disconnect()
        self._clients.clear()
        self._connected.clear()
        self._sdk_sessions.clear()
        self._active.clear()


async def _drain(source: AsyncIterator[Any], stop: asyncio.Event) -> AsyncIterator[Any]:
    """转发 SDK 消息流，停止标记置位后尽快收尾（不硬杀，给 SDK 自己收的机会）。"""
    async for msg in source:
        yield msg
        if stop.is_set() and isinstance(msg, (ResultMessage, SystemMessage)):
            break
