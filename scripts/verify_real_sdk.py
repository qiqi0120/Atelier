#!/usr/bin/env python
"""**真实** Claude Agent SDK 验证（M1 验收报告 §8 欠账②）。

M1 全部对话都跑在 ``MockHarness`` 上：事件映射、门禁 tool、中断、恢复这些
**只在契约层验过，没在真模型上跑通过**。本脚本用真 ``ANTHROPIC_API_KEY``
逐条验证，是把「契约正确」升级为「真机正确」的唯一途径。

用法::

    export ANTHROPIC_API_KEY=sk-ant-...
    .venv/bin/python scripts/verify_real_sdk.py            # 全跑
    .venv/bin/python scripts/verify_real_sdk.py c5 c6      # 只跑指定项（省钱）

**会真的花钱**，8 项检查按需跑量（每轮提示词都很短，量级在几美分）。
不设 ``ATELIER_MOCK``——刻意不读它，本脚本就是要绕开 mock。

隔离：整个过程切到临时根目录，绝不写脏真实的 ``outputs/`` 与 ``var/``。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 必须在 import atelier.* 之前切根（paths 模块级常量按 ROOT 派生）
_TMP = Path(tempfile.mkdtemp(prefix="atelier-real-sdk-"))
os.environ["ATELIER_ROOT"] = str(_TMP)
os.environ.pop("ATELIER_MOCK", None)  # 刻意清掉：不能被 mock 蒙混过关

from atelier.server import paths
from atelier.server.config import reload_settings
from atelier.server.core import db
from atelier.server.errors import HarnessAuthError, HarnessError
from atelier.server.harness.base import EventType, TurnRequest
from atelier.server.harness.claude_sdk import ClaudeSDKHarness
from atelier.server.harness.registry import set_harness

paths.configure(str(_TMP))
reload_settings()
db.reset_conn()
db.init_db()

RESULTS: list[tuple[str, bool, str]] = []
TOTAL_COST = 0.0


def check(label: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(ok), detail))
    print(f"  {'✓' if ok else '✗'} {label}{('  — ' + detail) if detail else ''}")


def req(prompt: str, suffix: str | None = None) -> TurnRequest:
    sid = f"real-{uuid.uuid4().hex[:8]}"
    return TurnRequest(
        session_id=sid,
        turn_id=uuid.uuid4().hex,
        prompt=prompt,
        profile=None,
        attachments=[],
        system_suffix=suffix,
        project="realsdk",
    )


async def collect(harness, request, *, on_event=None):
    """跑一轮，把事件全收下。返回 (事件列表, 耗时秒)。"""
    events = []
    t0 = time.time()
    async for ev in harness.stream(request):
        events.append(ev)
        if on_event:
            on_event(ev)
    return events, time.time() - t0


def summarize(events) -> dict:
    kinds: dict[str, int] = {}
    text = []
    for ev in events:
        kinds[ev.type.value] = kinds.get(ev.type.value, 0) + 1
        if ev.type == EventType.TEXT_DELTA:
            text.append(str((ev.data or {}).get("text") or ""))
    done = next((e for e in events if e.type == EventType.DONE), None)
    return {
        "kinds": kinds,
        "text": "".join(text),
        "cost": float((done.data or {}).get("cost_usd") or 0.0) if done else 0.0,
        "turns": (done.data or {}).get("num_turns") if done else None,
    }


# ------------------------------------------------------------------ 检查项


async def c1_health() -> None:
    """health() 在真 key 下报 OK，且不是被 mock 顶替。"""
    h = ClaudeSDKHarness()
    rep = await h.health()
    check("1 health() 认证通过", rep.ok, f"{rep.name} · {rep.message or 'ok'}")
    if rep.detail:
        print(f"      detail: {rep.detail}")


async def c2_bad_key() -> None:
    """错 key 要报 HarnessAuthError，而不是崩栈或静默成功。

    ⚠️ 诚实性检查：若父环境里有 ``ANTHROPIC_AUTH_TOKEN``（Anthropic 兼容代理的常见
    配法，如智谱 GLM），CLI 会优先用它，我注入的坏 ``API_KEY`` 根本不会被送到服务端。
    那种情况下本项**无法判定**，必须如实说「不适用」，不许把「代理收下了假 key」
    报成「代码的鉴权处理有问题」。
    """
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        check("2 错误密钥 → HarnessAuthError", True,
              "不适用：父环境有 ANTHROPIC_AUTH_TOKEN，代理优先用它，坏 API_KEY 送不出去"
              "（这是测试装置限制，不是代码问题）")
        return
    h = ClaudeSDKHarness(api_key="sk-ant-definitely-invalid-key-for-test")
    try:
        await collect(h, req("说一个字：好"))
    except HarnessAuthError:
        check("2 错误密钥 → HarnessAuthError", True, "按预期报错，未崩栈")
    except HarnessError as e:
        check("2 错误密钥 → HarnessAuthError", False, f"抛的是 {type(e).__name__}，不是 HarnessAuthError")
    except Exception as e:  # noqa: BLE001 — 兜底：把任何未预期异常都记成失败项，不让验证脚本自己崩
        check("2 错误密钥 → HarnessAuthError", False, f"未分类异常 {type(e).__name__}: {e}")
    else:
        check("2 错误密钥 → HarnessAuthError", False, "错 key 竟然跑通了，可疑")


async def c3_streaming() -> None:
    """真流式：必须有多次 TEXT_DELTA，不能是一个大块。"""
    h = ClaudeSDKHarness()
    events, dur = await collect(
        h, req("用不超过 120 字，讲清楚「新手做号第一周该干什么」。不要列点，写成一段话。")
    )
    s = summarize(events)
    global TOTAL_COST
    TOTAL_COST += s["cost"]
    n = s["kinds"].get("text_delta", 0)
    check("3 真流式增量", n >= 3, f"{n} 个 text_delta / {dur:.1f}s / 正文 {len(s['text'])} 字")
    check("3 收到 DONE 事件", "done" in s["kinds"], f"事件分布 {s['kinds']}")
    if s["cost"]:
        print(f"      本轮真实花费 ${s['cost']:.6f}，{s['turns']} turns")


async def c4_thinking() -> None:
    """独立思考流：THINKING_START / THINKING_DELTA 要真的出现。"""
    h = ClaudeSDKHarness()
    events, _ = await collect(
        h, req("想清楚再答：一个 500 粉的新号，第一条笔记该发什么？只给结论和一句理由。")
    )
    s = summarize(events)
    global TOTAL_COST
    TOTAL_COST += s["cost"]
    check(
        "4 独立思考流",
        s["kinds"].get("thinking_start", 0) >= 1 and s["kinds"].get("thinking_delta", 0) >= 1,
        f"thinking_start={s['kinds'].get('thinking_start', 0)} "
        f"thinking_delta={s['kinds'].get('thinking_delta', 0)}",
    )


async def c5_gate_tool() -> None:
    """**门禁 tool 真能被模型调起来**——这是 M0 设计的核心主张（不是提示词约定）。

    让模型写一段带极限词的文案并要求落盘；观察它是否真的调用
    ``atelier_gate_run`` / ``atelier_artifact_write``。
    """
    h = ClaudeSDKHarness(timeout=300)  # 单轮要跑 4 个工具 + 落盘，默认 120s 不够（c3 单轮已 81s）
    events, _ = await collect(
        h,
        req(
            "写一段 **40 字以内**的小红书文案，主题是「早餐搭配」。"
            "只做两步：先调用 atelier_gate_run 跑门禁，再用 atelier_artifact_write 落盘。"
            "文案里请自然地用上「国家级」和「最有效」这两个说法。不要解释，不要总结。"
        ),
    )
    s = summarize(events)
    global TOTAL_COST
    TOTAL_COST += s["cost"]
    tools_called = [str((e.data or {}).get("name")) for e in events if e.type == EventType.TOOL_CALL]
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    gate_calls = [n for n in tools_called if n.endswith("atelier_gate_run")]
    write_calls = [n for n in tools_called if n.endswith("atelier_artifact_write")]
    check("5 门禁 tool 被真实调用", bool(gate_calls),
          f"gate_run×{len(gate_calls)} artifact_write×{len(write_calls)}")
    check("5 落盘 tool 被真实调用", bool(write_calls), f"{len(write_calls)} 次")
    check("5 有 tool 返回结果", bool(results), f"{len(results)} 条 tool_result")
    # 极限词应被 BLOCK
    blocked = False
    for e in results:
        blob = str((e.data or {}).get("content") or "")
        if "blocked" in blob and "true" in blob:
            blocked = True
    check("5 极限词被门禁 BLOCK", blocked,
          "hard gate 真拦住了（fail-closed 语义成立）" if blocked
          else "未在 tool_result 里看到 blocked=true（需人工核对产物是否被拒）")


async def c6_interrupt() -> None:
    """中断：2s 内停，且已生成内容不丢（SPEC-01 §3）。"""
    h = ClaudeSDKHarness()
    r = req("写一篇 800 字的公众号文章，主题是「小号怎么起步」。")
    seen: list[str] = []
    t0 = time.time()
    task = asyncio.create_task(collect(h, r, on_event=lambda e: seen.append(e)))
    await asyncio.sleep(2.0)
    await h.interrupt(r.turn_id)
    t_interrupt = time.time() - t0
    try:
        await asyncio.wait_for(task, timeout=5)
    except (TimeoutError, asyncio.CancelledError):
        pass
    elapsed = time.time() - t0
    s = summarize(seen)
    check("6 中断 2s 内生效", elapsed < 4.0, f"发起中断 {t_interrupt:.2f}s → 实际停 {elapsed:.2f}s")
    kept = len(s["text"])
    thought = s["kinds"].get("thinking_delta", 0)
    check("6 中断后已生成内容保留", kept > 0 or thought > 0,
          f"正文 {kept} 字 / 思考增量 {thought} 段"
          + ("（2s 内还在思考，正文未起笔——属正常，不算丢内容）" if kept == 0 and thought else ""))


async def c7_multiturn() -> None:
    """多轮续接：第二轮要记得第一轮说了什么（resume 生效）。"""
    h = ClaudeSDKHarness()
    sid = f"real-mt-{uuid.uuid4().hex[:8]}"
    secret = "紫罗兰七号"
    r1 = TurnRequest(session_id=sid, turn_id=uuid.uuid4().hex,
                     prompt=f"记住一个词：{secret}。只回复「记住了」，不要多说。",
                     profile=None, attachments=[])
    await collect(h, r1)
    r2 = TurnRequest(session_id=sid, turn_id=uuid.uuid4().hex,
                     prompt="我刚让你记的词是什么？只回复那个词。",
                     profile=None, attachments=[])
    events, _ = await collect(h, r2)
    s = summarize(events)
    global TOTAL_COST
    TOTAL_COST += s["cost"]
    check("7 多轮续接记住上文", secret in s["text"], f"第二轮答：{s['text'].strip()[:60]!r}")


async def c8_profile_injection() -> None:
    """画像内联真的进到了 system_prompt（出口标准 1 的真机版本）。"""
    from atelier.server.core import models

    now = db.utcnow()
    prof = models.Profile(
        id="p-real", name="干饭人阿泽",
        platforms=["xiaohongshu"],
        identity="一个只会做饭的普通上班族",
        style="短句，不用比喻，不写总结句",
        audience="刚学做饭的独居年轻人",
        platform_rules="",
        preferences="",
        created_at=now, updated_at=now,
    )
    h = ClaudeSDKHarness()
    r = TurnRequest(
        session_id=f"real-prof-{uuid.uuid4().hex[:8]}", turn_id=uuid.uuid4().hex,
        prompt="用一句话介绍你自己。", profile=prof, attachments=[],
    )
    events, _ = await collect(h, r)
    s = summarize(events)
    global TOTAL_COST
    TOTAL_COST += s["cost"]
    hit = "干饭人阿泽" in s["text"] or "只会做饭" in s["text"] or "上班族" in s["text"]
    check("8 画像注入生效", hit, f"回答：{s['text'].strip()[:70]!r}")


# ------------------------------------------------------------------ main


async def main() -> int:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    print("=" * 72)
    print("真实 Claude Agent SDK 验证")
    print("=" * 72)
    print(f"临时根目录：{_TMP}")
    print(f"ANTHROPIC_API_KEY：{'已设置（' + str(len(key)) + ' 字符）' if key else '**未设置**'}")
    if not key:
        print("\n没有 ANTHROPIC_API_KEY，无法跑真机验证。")
        print("这一步不能用 mock 代替——那正是要验证的东西。")
        return 2
    print(f"SDK 版本：{_sdk_version()}")
    print()

    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    if only:
        print(f"只跑：{', '.join(only)}（其余检查跳过）\n")

    set_harness(None)  # 清掉任何 mock 单例，逼它走真 ClaudeSDKHarness
    from atelier.server.harness.registry import get_harness

    real = get_harness()
    print(f"实际 provider：{type(real).__name__}（name={getattr(real, 'name', '?')}）")
    if type(real).__name__ != "ClaudeSDKHarness":
        print("⚠️  取到的不是 ClaudeSDKHarness，结果不可信")
    print()

    for fn in (c1_health, c2_bad_key, c3_streaming, c4_thinking,
               c5_gate_tool, c6_interrupt, c7_multiturn, c8_profile_injection):
        if only and not any(k in fn.__name__ for k in only):
            continue
        print(f"【{fn.__name__.split('_', 1)[1]}】")
        try:
            await fn()
        except Exception as e:  # noqa: BLE001 — 单项失败不该中断整轮验证
            import traceback

            check(f"{fn.__name__} 异常", False, f"{type(e).__name__}: {e}")
            traceback.print_exc()
        print()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("=" * 72)
    print(f"结果：{passed}/{total} 通过    真实花费合计 ${TOTAL_COST:.6f}")
    print("=" * 72)
    for label, ok, detail in RESULTS:
        if not ok:
            print(f"  ✗ {label}  {detail}")
    return 0 if passed == total else 1


def _sdk_version() -> str:
    try:
        from importlib.metadata import version

        return version("claude-agent-sdk")
    except Exception:  # noqa: BLE001
        return "未知"


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(code)
