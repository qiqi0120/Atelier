"""SPEC-01 §3/§4 · Harness 测试。

**不依赖 API key**：主路径全部走 :class:`MockHarness`（``ATELIER_MOCK=1``）。
``claude_sdk`` 只测**不需要 key 的部分**：消息映射（用真实 SDK 对象，保证与 0.2.163 对得上）、
选项构造、鉴权错误分支。

其中一条测试直接读源码断言 ``harness/base.py`` 里没有 ``claude_agent_sdk``——
这是 SPEC-01 §3 的硬性要求，靠人记着迟早会破，交给测试守。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from atelier.server import paths
from atelier.server.errors import HarnessAuthError, HarnessError, SessionBusy
from atelier.server.harness import registry as harness_registry
from atelier.server.harness.base import (
    EventType,
    Harness,
    HealthReport,
    MockHarness,
    TurnEvent,
    TurnRecorder,
    TurnRequest,
    read_turn_events,
)
from atelier.server.harness.claude_sdk import (
    ClaudeSDKHarness,
    build_system_prompt,
    events_from_message,
)
from atelier.server.harness.tools import MCP_SERVER_NAME, allowed_tool_names

# SPEC-01 §3 冻结的枚举值
FROZEN_EVENT_TYPES = {
    "thinking_start", "thinking_delta", "text_delta", "tool_call", "tool_result",
    "question", "artifact", "gate_result", "done", "error",
}


def _imports_sdk(node: object) -> bool:
    """AST 节点是不是顶层 SDK import（``import x`` 与 ``from x import y`` 都算）。"""
    import ast

    if isinstance(node, ast.Import):
        return any(a.name.split(".")[0] == "claude_agent_sdk" for a in node.names)
    if isinstance(node, ast.ImportFrom):
        return bool(node.module) and node.module.split(".")[0] == "claude_agent_sdk"
    return False


def _req(**kw: object) -> TurnRequest:
    base: dict[str, object] = {"session_id": "s1", "turn_id": "t1", "prompt": "写一篇探店", "profile": None}
    base.update(kw)
    return TurnRequest(**base)  # type: ignore[arg-type]


class TestContract:
    def test_base_module_is_sdk_free(self) -> None:
        """验收项：harness/base.py 里 grep 不到 SDK 的 import 名。"""
        src = Path("atelier/server/harness/base.py")
        assert "claude_agent_sdk" not in src.read_text("utf-8"), "base.py 出现 SDK import 名，抽象就漏了"

    def test_only_claude_sdk_imports_sdk(self) -> None:
        """整个 harness 层只有 claude_sdk.py 在模块顶层 import SDK。

        用 AST 判「真的 import 了」，而不是子串匹配——``tools.py``/``claude_sdk.py``
        里有函数体内的局部 import（``@tool`` 包装用），那是刻意允许的。
        """
        import ast

        offenders = []
        for p in sorted(Path("atelier/server/harness").glob("*.py")):
            tree = ast.parse(p.read_text("utf-8"))
            for node in tree.body:  # 只看模块顶层
                if _imports_sdk(node) and p.name != "claude_sdk.py":
                    offenders.append(p.name)
        assert offenders == [], f"这些文件在顶层 import 了 SDK：{offenders}"

    def test_tools_and_claude_sdk_use_lazy_sdk_import(self) -> None:
        """tools.py / claude_sdk.py 的局部 import 必须在函数体内。"""
        import ast

        for name in ("tools.py", "claude_sdk.py"):
            tree = ast.parse(Path("atelier/server/harness", name).read_text("utf-8"))
            top_level = [
                n
                for n in tree.body
                if _imports_sdk(n)
            ]
            if name == "tools.py":
                assert top_level == [], "tools.py 必须保持模块顶层 SDK-free（单测要能直接调 fn）"
            else:
                assert len(top_level) == 1, "claude_sdk.py 允许且只允许一处顶层 SDK import"

    def test_event_type_values_frozen(self) -> None:
        assert {e.value for e in EventType} == FROZEN_EVENT_TYPES

    def test_turn_event_roundtrip(self) -> None:
        ev = TurnEvent(EventType.TEXT_DELTA, "t1", {"text": "你好"})
        d = ev.to_dict()
        assert d == {"type": "text_delta", "turn_id": "t1", "data": {"text": "你好"}}
        assert TurnEvent.from_dict(d) == ev

    def test_turn_event_text_helper(self) -> None:
        assert TurnEvent(EventType.TEXT_DELTA, "t", {"text": "x"}).text() == "x"
        assert TurnEvent(EventType.DONE, "t").text() == ""

    def test_turn_request_defaults(self) -> None:
        r = _req()
        assert r.attachments == []
        assert r.system_suffix is None
        assert r.project is None
        assert r.attachments_block() == ""

    def test_attachments_block(self) -> None:
        from atelier.server.core.models import Attachment

        r = _req(attachments=[Attachment(id="a", kind="image", path="p/x.png", name="x.png", size=1, mime="image/png")])
        block = r.attachments_block()
        assert "x.png" in block and "image/png" in block

    def test_harness_protocol_is_runtime_checkable(self) -> None:
        assert isinstance(MockHarness(), Harness)


class TestMockStreaming:
    async def test_event_sequence(self, atelier_root: Path) -> None:
        h = MockHarness(delay=0)
        events = [e async for e in h.stream(_req())]
        types = [e.type for e in events]
        assert types[0] == EventType.THINKING_START
        assert EventType.THINKING_DELTA in types
        assert types[-1] == EventType.DONE
        assert types.count(EventType.TEXT_DELTA) >= 3
        assert all(e.turn_id == "t1" for e in events)

    async def test_thinking_stream_is_separate_from_text(self, atelier_root: Path) -> None:
        """PRD F-B1：思考流与正文流是两条独立事件。"""
        h = MockHarness(delay=0)
        events = [e async for e in h.stream(_req())]
        thinking = "".join(e.data.get("text", "") for e in events if e.type == EventType.THINKING_DELTA)
        text = "".join(e.data.get("text", "") for e in events if e.type == EventType.TEXT_DELTA)
        assert "技能库" in thinking
        assert text and thinking != text

    async def test_done_carries_full_text(self, atelier_root: Path) -> None:
        h = MockHarness(delay=0)
        events = [e async for e in h.stream(_req())]
        done = events[-1]
        assert done.type == EventType.DONE
        assert done.data["text"] == "".join(
            e.data.get("text", "") for e in events if e.type == EventType.TEXT_DELTA
        )
        assert done.data["interrupted"] is False

    async def test_profile_name_shows_up_in_reply(self, atelier_root: Path) -> None:
        """画像是内联进这一轮的（PRD 4.2）。"""
        from datetime import UTC, datetime

        from atelier.server.core.models import Profile

        now = datetime.now(UTC)
        p = Profile(id="p1", name="咖啡老王", platforms=["xhs"], created_at=now, updated_at=now)
        h = MockHarness(delay=0)
        events = [e async for e in h.stream(_req(profile=p))]
        assert any("咖啡老王" in e.data.get("text", "") for e in events)

    async def test_events_are_persisted_to_jsonl(self, atelier_root: Path) -> None:
        h = MockHarness(delay=0)
        events = [e async for e in h.stream(_req())]
        log = paths.turn_log("s1", "t1")
        assert log.exists()
        lines = [x for x in log.read_text("utf-8").splitlines() if x.strip()]
        assert len(lines) == len(events)

    async def test_resume_from_memory(self, atelier_root: Path) -> None:
        h = MockHarness(delay=0)
        events = [e async for e in h.stream(_req())]
        assert await h.resume("t1") == events

    async def test_resume_from_disk_when_cache_cold(self, atelier_root: Path) -> None:
        """断线重连：新进程里没有内存缓存，只能从 jsonl 重建（PRD F-B6）。"""
        h1 = MockHarness(delay=0)
        events = [e async for e in h1.stream(_req())]
        h2 = MockHarness(delay=0)  # 模拟新进程
        assert await h2.resume("t1") == events

    async def test_resume_unknown_turn_is_empty(self, atelier_root: Path) -> None:
        assert await MockHarness().resume("never-existed") == []

    def test_read_turn_events_skips_bad_lines(self, atelier_root: Path) -> None:
        log = paths.turn_log("s2", "t2")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"done","turn_id":"t2","data":{}}\n坏行\n\n', encoding="utf-8")
        assert [e.type for e in read_turn_events("t2")] == [EventType.DONE]

    async def test_health(self, atelier_root: Path) -> None:
        r = await MockHarness().health()
        assert isinstance(r, HealthReport)
        assert r.ok is True
        assert r.detail["mock"] is True


class TestMockInterrupt:
    async def test_interrupt_stops_within_2s(self, atelier_root: Path) -> None:
        """验收项：停止生成 2s 内生效（PRD F-B5）。"""
        h = MockHarness(delay=0.1)
        got: list[TurnEvent] = []

        async def consume() -> None:
            async for e in h.stream(_req(session_id="sx", turn_id="tx")):
                got.append(e)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.15)
        t0 = time.monotonic()
        await h.interrupt("tx")
        elapsed = time.monotonic() - t0
        await asyncio.wait_for(task, timeout=2)

        assert elapsed < 2.0, f"中断花了 {elapsed:.2f}s"
        assert got[-1].type == EventType.DONE
        assert got[-1].data["interrupted"] is True

    async def test_interrupt_stops_text_emission(self, atelier_root: Path) -> None:
        h = MockHarness(delay=0.08)
        got: list[TurnEvent] = []

        async def consume() -> None:
            async for e in h.stream(_req(session_id="sy", turn_id="ty")):
                got.append(e)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.2)
        await h.interrupt("ty")
        await asyncio.wait_for(task, timeout=2)
        deltas = [e for e in got if e.type == EventType.TEXT_DELTA]
        assert len(deltas) < len(MockHarness().chunks) + 1

    async def test_interrupted_turn_is_persisted(self, atelier_root: Path) -> None:
        h = MockHarness(delay=0.08)
        got: list[TurnEvent] = []

        async def consume() -> None:
            async for e in h.stream(_req(session_id="sz", turn_id="tz")):
                got.append(e)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.2)
        await h.interrupt("tz")
        await asyncio.wait_for(task, timeout=2)
        resumed = await MockHarness().resume("tz")
        assert resumed[-1].data["interrupted"] is True

    async def test_interrupt_unknown_turn_is_noop(self, atelier_root: Path) -> None:
        await MockHarness().interrupt("never-started")

    async def test_aclose_does_not_kill_consumer(self, atelier_root: Path) -> None:
        """aclose 只置停止标记，不能把消费方 task 一起 cancel 掉。"""
        h = MockHarness(delay=0)
        events = [e async for e in h.stream(_req())]
        assert events  # 主 task 活着本身就是断言
        await h.aclose()


class TestSessionBusy:
    async def test_concurrent_turn_on_same_session_raises(self, atelier_root: Path) -> None:
        """PRD F-B12：一个 session 同时只允许一个活跃 turn。"""
        h = MockHarness(delay=0.05)

        async def hold() -> None:
            async for _ in h.stream(_req(session_id="busy", turn_id="t1")):
                await asyncio.sleep(0.01)

        task = asyncio.create_task(hold())
        await asyncio.sleep(0.06)
        with pytest.raises(SessionBusy) as ei:
            async for _ in h.stream(_req(session_id="busy", turn_id="t2")):
                pass
        assert ei.value.http == 409
        assert ei.value.detail["running_turn_id"] == "t1"
        await task

    async def test_same_turn_id_is_allowed(self, atelier_root: Path) -> None:
        h = MockHarness(delay=0.02)
        seen = []

        async def hold() -> None:
            async for _ in h.stream(_req(session_id="same", turn_id="t1")):
                seen.append(1)
                await asyncio.sleep(0.01)

        task = asyncio.create_task(hold())
        await asyncio.sleep(0.03)
        async for _ in h.stream(_req(session_id="same", turn_id="t1")):
            pass  # 同一个 turn_id 重入不报忙
        await task

    async def test_session_released_after_turn(self, atelier_root: Path) -> None:
        h = MockHarness(delay=0)
        async for _ in h.stream(_req(session_id="rel", turn_id="t1")):
            pass
        async for _ in h.stream(_req(session_id="rel", turn_id="t2")):
            pass  # 上一轮结束后应能开新轮


class TestRecorder:
    def test_write_and_read(self, atelier_root: Path) -> None:
        r = TurnRecorder("s3", "t3")
        r.write(TurnEvent(EventType.TEXT_DELTA, "t3", {"text": "a"}))
        r.write(TurnEvent(EventType.DONE, "t3", {"text": "a"}))
        assert [e.type for e in r.read_all()] == [EventType.TEXT_DELTA, EventType.DONE]
        assert r.path == paths.turn_log("s3", "t3")

    def test_read_missing_file_is_empty(self, atelier_root: Path) -> None:
        assert TurnRecorder("s4", "t4").read_all() == []


class TestRegistry:
    def test_mock_selected_when_env_set(self, atelier_root: Path) -> None:
        harness_registry.reset_harness()
        assert harness_registry.get_harness().name == "mock"

    def test_explicit_name(self, atelier_root: Path) -> None:
        assert harness_registry.create_harness("mock").name == "mock"

    def test_unknown_provider_raises_harness_error(self, atelier_root: Path) -> None:
        with pytest.raises(HarnessError) as ei:
            harness_registry.create_harness("nope")
        assert ei.value.http == 502
        assert "mock" in ei.value.detail["available"]

    def test_claude_sdk_provider_loads(self, atelier_root: Path) -> None:
        h = harness_registry.create_harness("claude_sdk")
        assert h.name == "claude_sdk"

    def test_set_and_reset(self, atelier_root: Path) -> None:
        sentinel = MockHarness()
        harness_registry.set_harness(sentinel)
        assert harness_registry.get_harness() is sentinel
        assert harness_registry.current_harness() is sentinel
        harness_registry.reset_harness()
        assert harness_registry.current_harness() is None

    def test_available_providers(self) -> None:
        assert harness_registry.available_providers() == ["claude_sdk", "mock"]


class TestClaudeSdkMapping:
    """用**真实 SDK 0.2.163 的对象**测映射，SDK 升级改坏了这里会立刻红。"""

    def test_text_block(self) -> None:
        from claude_agent_sdk import AssistantMessage, TextBlock

        msg = AssistantMessage(content=[TextBlock(text="你好")], model="m")
        evs = events_from_message(msg, "t1")
        assert [e.type for e in evs] == [EventType.TEXT_DELTA]
        assert evs[0].data["text"] == "你好"

    def test_thinking_block_needs_signature(self) -> None:
        """实测：ThinkingBlock(thinking, signature) 两个参数都是必填。"""
        from claude_agent_sdk import AssistantMessage, ThinkingBlock

        msg = AssistantMessage(content=[ThinkingBlock(thinking="想一下", signature="sig")], model="m")
        evs = events_from_message(msg, "t1")
        assert [e.type for e in evs] == [EventType.THINKING_DELTA]
        assert evs[0].data["text"] == "想一下"

    def test_tool_use_and_result(self) -> None:
        from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock

        msg = AssistantMessage(
            content=[
                ToolUseBlock(id="tu1", name="atelier_gate_run", input={"text": "x"}),
                ToolResultBlock(tool_use_id="tu1", content="通过", is_error=False),
            ],
            model="m",
        )
        evs = events_from_message(msg, "t1")
        assert [e.type for e in evs] == [EventType.TOOL_CALL, EventType.TOOL_RESULT]
        assert evs[0].data["name"] == "atelier_gate_run"
        assert evs[0].data["input"] == {"text": "x"}
        assert evs[1].data["tool_use_id"] == "tu1"
        assert evs[1].data["is_error"] is False

    def test_tool_result_in_user_message_is_not_dropped(self) -> None:
        """回归：SDK 把 ToolResultBlock 装在 **UserMessage** 里回传（user 角色）。

        上面那条用例把它塞进 AssistantMessage——那不是 SDK 真实产生的形状，
        所以「UserMessage 整个 return out、工具结果被丢弃」这个 bug 一直没被照到。
        真机验证实测：模型调了 3 次门禁 tool，却收到 **0 条 tool_result**，
        后果是前端只看到 TOOL_CALL、永远等不到结果，门禁块一直转圈。
        """
        from claude_agent_sdk import TextBlock, ToolResultBlock, UserMessage

        msg = UserMessage(
            content=[
                ToolResultBlock(
                    tool_use_id="tu9",
                    content='{"blocked": true, "level": "block"}',
                    is_error=False,
                ),
                TextBlock(text="工具结果之后的用户侧文本"),
            ],
        )
        evs = events_from_message(msg, "t1")
        assert [e.type for e in evs] == [EventType.TOOL_RESULT], "UserMessage 里的工具结果必须被映射出来"
        assert evs[0].data["tool_use_id"] == "tu9"
        assert "blocked" in str(evs[0].data["content"])
        assert evs[0].data["is_error"] is False

    def test_assistant_text_not_duplicated_when_streamed(self) -> None:
        """回归：开了 ``include_partial_messages`` 后正文会**完整出现两次**。

        SDK 先逐 token 发 ``StreamEvent``，末尾再用一条 ``AssistantMessage``
        把同一份正文整块重发。两个源都映射的话，界面上每段话出现两遍
        （真机实测：短增量累计 154 字，随后又来 32 + 122 = 154 字的整段）。

        传 ``streamed=True`` 应跳过重复的 Text/Thinking 块，
        但 **ToolUseBlock 仍要保留**——工具入参没有 StreamEvent 对应物。
        """
        from claude_agent_sdk import AssistantMessage, TextBlock, ThinkingBlock, ToolUseBlock

        msg = AssistantMessage(
            content=[
                ThinkingBlock(thinking="想了一遍", signature="sig"),
                TextBlock(text="这是正文"),
                ToolUseBlock(id="t1", name="atelier_gate_run", input={"text": "x"}),
            ],
            model="m",
        )
        dup = events_from_message(msg, "t1")
        assert [e.type for e in dup] == [
            EventType.THINKING_DELTA, EventType.TEXT_DELTA, EventType.TOOL_CALL,
        ], "未标记 streamed 时行为应与旧版一致"

        deduped = events_from_message(msg, "t1", streamed=True)
        assert [e.type for e in deduped] == [EventType.TOOL_CALL], "去重后只应保留工具调用"
        assert deduped[0].data["name"] == "atelier_gate_run"

    def test_stream_event_text_delta(self) -> None:
        from claude_agent_sdk import StreamEvent

        msg = StreamEvent(
            uuid="u", session_id="s",
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "增量"}},
        )
        evs = events_from_message(msg, "t1")
        assert [e.type for e in evs] == [EventType.TEXT_DELTA]
        assert evs[0].data["text"] == "增量"

    def test_stream_event_thinking_delta(self) -> None:
        from claude_agent_sdk import StreamEvent

        msg = StreamEvent(
            uuid="u", session_id="s",
            event={"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "在想"}},
        )
        evs = events_from_message(msg, "t1")
        assert [e.type for e in evs] == [EventType.THINKING_DELTA]

    @pytest.mark.parametrize("event", [
        {"type": "message_start"},
        {"type": "content_block_start", "content_block": {"type": "text"}},
        {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "{"}},
        {"type": "unknown_thing"},
    ])
    def test_non_text_stream_events_ignored(self, event: dict) -> None:
        from claude_agent_sdk import StreamEvent

        assert events_from_message(StreamEvent(uuid="u", session_id="s", event=event), "t1") == []

    def test_result_message_success(self) -> None:
        from claude_agent_sdk import ResultMessage

        msg = ResultMessage(
            subtype="success", duration_ms=10, duration_api_ms=5, is_error=False, num_turns=2,
            session_id="sdk-1", total_cost_usd=0.01, usage={}, result="完成",
        )
        evs = events_from_message(msg, "t1")
        assert [e.type for e in evs] == [EventType.DONE]
        assert evs[0].data["num_turns"] == 2
        assert evs[0].data["is_error"] is False

    def test_result_message_error_yields_error_then_done(self) -> None:
        from claude_agent_sdk import ResultMessage

        msg = ResultMessage(
            subtype="error_during_execution", duration_ms=1, duration_api_ms=1, is_error=True,
            num_turns=1, session_id="s", total_cost_usd=0.0, usage={}, result="炸了",
        )
        evs = events_from_message(msg, "t1")
        assert [e.type for e in evs] == [EventType.ERROR, EventType.DONE]
        assert evs[0].data["message"] == "炸了"

    def test_system_and_user_messages_ignored(self) -> None:
        from claude_agent_sdk import SystemMessage, UserMessage

        assert events_from_message(SystemMessage(subtype="init", data={}), "t1") == []
        assert events_from_message(UserMessage(content="hi"), "t1") == []

    def test_unknown_message_type_ignored(self) -> None:
        assert events_from_message(object(), "t1") == []


class TestClaudeSdkOptions:
    def test_auth_error_without_key(self, atelier_root: Path, clean_env: None) -> None:
        """缺 ANTHROPIC_API_KEY → HarnessAuthError（不是裸栈，指向设置页）。"""
        h = ClaudeSDKHarness(api_key=None)
        with pytest.raises(HarnessAuthError) as ei:
            h.build_options(_req())
        assert ei.value.http == 502
        assert "设置" in (ei.value.hint or "")

    def test_options_carry_mcp_tools_and_system_prompt(self, atelier_root: Path) -> None:
        h = ClaudeSDKHarness(api_key="sk-test-key")
        opts = h.build_options(_req())
        assert opts.system_prompt and "Atelier" in str(opts.system_prompt)
        assert opts.allowed_tools == allowed_tool_names()
        assert MCP_SERVER_NAME in opts.mcp_servers
        assert opts.include_partial_messages is True
        assert opts.env["ANTHROPIC_API_KEY"] == "sk-test-key"
        assert str(opts.cwd) == str(paths.ROOT)

    def test_native_thinking_enabled(self, atelier_root: Path) -> None:
        """PRD F-B1 走原生能力：thinking 配置被打开。

        **回归**：曾经写成 ``ThinkingConfigAdaptive()``，但它是 TypedDict（类型）
        不是类，调用得到空 dict ``{}``——非 None 所以旧断言照样通过，可 SDK 的
        ``_build_command`` 要读 ``t["type"]``，真连时直接 ``KeyError: 'type'``。
        所以这里必须断言**结构**，不能只断言 not None。
        """
        h = ClaudeSDKHarness(api_key="sk-test-key")
        opts = h.build_options(_req())
        assert opts.thinking is not None
        assert opts.thinking["type"] == "adaptive", f"thinking 缺 type 键，SDK 读命令时会崩：{opts.thinking!r}"
        # thinking 与 max_thinking_tokens 同时给时 SDK 只认前者，别设成误导性的双份
        assert opts.max_thinking_tokens is None

    def test_thinking_config_survives_sdk_command_builder(self, atelier_root: Path) -> None:
        """把 build_options 的结果喂给 SDK 自己的命令构造器——真跑前就把形状问题挡住。

        这是 M1 缺的那道防线：mock 永远走不到命令构造这一步。
        """
        from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

        h = ClaudeSDKHarness(api_key="sk-test-key")
        opts = h.build_options(_req())
        transport = SubprocessCLITransport(prompt="hi", options=opts)
        transport._cli_path = transport._find_cli()  # 只解析路径，不真连
        cmd = transport._build_command()
        assert "--thinking" in cmd and "adaptive" in cmd, cmd

    def test_stream_does_not_iterate_over_wait_for_coroutine(self, atelier_root: Path) -> None:
        """回归：``async for x in asyncio.wait_for(gen, t)`` 是错的，wait_for 返回协程。

        M1 全部跑 MockHarness（有自己的 stream），这条路径从未被执行过，
        于是每一条**真实**对话都会在第一轮抛
        ``TypeError: 'async for' requires an object with __aiter__``。
        这里直接验包装器能正常迭代并正确报总超时。
        """
        import asyncio

        from atelier.server.harness.claude_sdk import _aiter_with_total_timeout

        async def gen():
            for i in range(3):
                yield i

        async def _ok():
            return [x async for x in _aiter_with_total_timeout(gen(), timeout=5)]

        assert asyncio.run(_ok()) == [0, 1, 2]

        async def _slow():
            async def gen2():
                yield 0
                await asyncio.sleep(10)
                yield 1
            return [x async for x in _aiter_with_total_timeout(gen2(), timeout=0.2)]

        with pytest.raises(TimeoutError):
            asyncio.run(_slow())

    def test_extra_options_override_defaults(self, atelier_root: Path) -> None:
        """扩展点：上层挂 skills / output_format 用，不必改本文件。"""
        h = ClaudeSDKHarness(
            api_key="sk-test-key",
            extra_options={"model": "claude-x", "skills": ["all"], "output_format": {"type": "json"}},
        )
        opts = h.build_options(_req())
        assert opts.model == "claude-x"
        assert opts.skills == ["all"]
        assert opts.output_format == {"type": "json"}

    def test_resume_carried_on_second_turn(self, atelier_root: Path) -> None:
        h = ClaudeSDKHarness(api_key="sk-test-key")
        assert getattr(h.build_options(_req(), resume=None), "resume", None) is None
        assert h.build_options(_req(), resume="sdk-1").resume == "sdk-1"
        assert h.build_options(_req(), resume="sdk-1").continue_conversation is True

    async def test_health_reports_key_state(self, atelier_root: Path, clean_env: None) -> None:
        r = await ClaudeSDKHarness(api_key=None).health()
        assert r.ok is False
        assert r.detail["api_key"] == "未配置"
        r2 = await ClaudeSDKHarness(api_key="sk-test-key").health()
        assert r2.ok is True
        assert r2.detail["mcp_tools"] == 5

    def test_system_prompt_inlines_profile(self, atelier_root: Path) -> None:
        from datetime import UTC, datetime

        from atelier.server.core.models import Memory, Profile

        now = datetime.now(UTC)
        p = Profile(
            id="p1", name="咖啡老王", platforms=["xhs"], identity="十年咖啡师", style="克制",
            preferences="不吹牛", memories=[Memory(id="m", text="他爱用具体数字", source="归因", created_at=now)],
            created_at=now, updated_at=now,
        )
        sp = build_system_prompt(_req(profile=p))
        assert "咖啡老王" in sp
        assert "十年咖啡师" in sp
        assert "他爱用具体数字" in sp
        assert "技能库" in sp  # 每轮重申，对抗指令衰减

    def test_general_mode_profile_not_injected(self, atelier_root: Path) -> None:
        from datetime import UTC, datetime

        from atelier.server.core.models import Profile

        now = datetime.now(UTC)
        p = Profile(id="p1", name="不该出现", platforms=["xhs"], identity="x",
                    general_mode=True, created_at=now, updated_at=now)
        assert "不该出现" not in build_system_prompt(_req(profile=p))

    def test_system_suffix_replaces_default(self, atelier_root: Path) -> None:
        sp = build_system_prompt(_req(system_suffix="【本轮只写标题】"))
        assert "【本轮只写标题】" in sp
        assert "本轮提醒" not in sp
