"""SPEC-03 · 对话工作台域测试。

全部走 ``MockHarness`` 或本文件里的桩 harness，**不需要 API key**（``ATELIER_MOCK=1``）。

三条硬验收各有专门用例：

- ``test_interrupt_stops_within_2s``  —— F-B5：点击到界面停止 ≤ 2s
- ``test_resume_returns_all_events`` / ``test_resume_dedup_by_index`` —— F-B6：断线不丢、不重复
- ``test_question_answered_not_repeated`` —— F-B7：答过不再问

两类测试不要混在一个事件循环里：``client``（TestClient）跑在它自己的 portal loop 上，
asyncio 用例跑在 pytest-asyncio 的 loop 上。跨 loop 复用 asyncio.Queue 会炸，所以
API 层用例一律走 HTTP，manager 层用例一律走 :func:`asyncio`。
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from atelier.server import paths
from atelier.server.config import reload_settings
from atelier.server.core import db, models
from atelier.server.core.models import Attachment
from atelier.server.errors import PathEscapeError, SessionBusy
from atelier.server.harness import registry as harness_registry
from atelier.server.harness.base import EventType, HealthReport, TurnEvent, TurnRequest
from atelier.server.main import create_app
from atelier.server.sessions import manager as mgr
from atelier.server.sessions import store

JSON = {"Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# 桩 harness
# ---------------------------------------------------------------------------


class SlowHarness:
    """每片之间 sleep ``delay``，可以无限慢——测「2s 内停止」用。"""

    name = "slow"

    def __init__(self, *, delay: float = 0.3, chunks: int = 200) -> None:
        self.delay = delay
        self.chunks = chunks
        self.interrupted: list[str] = []

    async def stream(self, req: TurnRequest) -> AsyncIterator[TurnEvent]:
        yield TurnEvent(EventType.THINKING_START, req.turn_id, {"phase": "start"})
        for i in range(self.chunks):
            await asyncio.sleep(self.delay)
            yield TurnEvent(EventType.TEXT_DELTA, req.turn_id, {"text": f"第{i}片"})

    async def interrupt(self, turn_id: str) -> None:
        self.interrupted.append(turn_id)

    async def resume(self, turn_id: str) -> list[TurnEvent]:
        return []

    async def health(self) -> HealthReport:
        return HealthReport(name=self.name, ok=True)

    async def aclose(self) -> None:
        return None


class HangingHarness:
    """指定会话吐一片之后无限等（只在被 cancel 时才结束）；其余会话正常秒回。"""

    name = "hanging"

    def __init__(self, hang_sessions: set[str] | None = None) -> None:
        self.hang_sessions = hang_sessions
        self.release = asyncio.Event()

    def _hangs(self, session_id: str) -> bool:
        return self.hang_sessions is None or session_id in self.hang_sessions

    async def stream(self, req: TurnRequest) -> AsyncIterator[TurnEvent]:
        yield TurnEvent(EventType.TEXT_DELTA, req.turn_id, {"text": "开头"})
        if not self._hangs(req.session_id):
            yield TurnEvent(EventType.DONE, req.turn_id, {"text": "开头"})
            return
        await self.release.wait()
        yield TurnEvent(EventType.TEXT_DELTA, req.turn_id, {"text": "永远不会到这"})
        yield TurnEvent(EventType.DONE, req.turn_id, {"text": "开头"})

    async def interrupt(self, turn_id: str) -> None:
        self.release.set()

    async def resume(self, turn_id: str) -> list[TurnEvent]:
        return []

    async def health(self) -> HealthReport:
        return HealthReport(name=self.name, ok=True)

    async def aclose(self) -> None:
        return None


class QuestionHarness:
    """每一轮都先反问同一个 ``question_id``——模拟 agent 重复提问（F-B7）。"""

    name = "question"

    def __init__(self, question_id: str = "q_01") -> None:
        self.question_id = question_id
        self.raw_emitted: list[TurnEvent] = []

    async def stream(self, req: TurnRequest) -> AsyncIterator[TurnEvent]:
        evs = [
            TurnEvent(EventType.THINKING_START, req.turn_id, {"phase": "start"}),
            TurnEvent(
                EventType.QUESTION,
                req.turn_id,
                {
                    "question_id": self.question_id,
                    "text": "补一个信息，我出终版",
                    "options": [
                        {"key": "A", "label": "保持这个语气，直接出终版"},
                        {"key": "B", "label": "再狠一点，标题带争议性"},
                    ],
                    "multiple": False,
                },
            ),
            TurnEvent(EventType.TEXT_DELTA, req.turn_id, {"text": "先给你一版。"}),
            TurnEvent(EventType.DONE, req.turn_id, {"text": "先给你一版。"}),
        ]
        for ev in evs:
            self.raw_emitted.append(ev)
            yield ev

    async def interrupt(self, turn_id: str) -> None:
        return None

    async def resume(self, turn_id: str) -> list[TurnEvent]:
        return list(self.raw_emitted)

    async def health(self) -> HealthReport:
        return HealthReport(name=self.name, ok=True)

    async def aclose(self) -> None:
        return None


class ExplodingHarness:
    """stream() 同步就炸——测错误留痕（原则四）。"""

    name = "boom"

    def __init__(self) -> None:
        self.boom = True

    async def stream(self, req: TurnRequest) -> AsyncIterator[TurnEvent]:
        if self.boom:
            raise RuntimeError("provider 炸了")
        yield TurnEvent(EventType.DONE, req.turn_id, {})

    async def interrupt(self, turn_id: str) -> None:
        return None

    async def resume(self, turn_id: str) -> list[TurnEvent]:
        return []

    async def health(self) -> HealthReport:
        return HealthReport(name=self.name, ok=False)

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------------------
# 夹具 / 工具
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_manager() -> Iterator[None]:
    """每个用例一个干净的 manager + 默认 mock harness（避免跨用例串状态）。"""
    mgr.reset_manager()
    harness_registry.set_harness(None)
    yield
    mgr.reset_manager()
    harness_registry.set_harness(None)


@pytest.fixture
def client(atelier_root: Path) -> Iterator[TestClient]:
    app = create_app(settings=reload_settings())
    with TestClient(app) as c:
        yield c


def _new_session(client: TestClient, title: str | None = None) -> str:
    r = client.post("/api/chat/sessions", json={"title": title} if title else {}, headers=JSON)
    assert r.status_code == 200, r.text
    return str(r.json()["session"]["id"])


def _sse_events(body: str) -> list[dict[str, Any]]:
    """把 SSE 响应体解析成事件列表（跳过 ``:`` 注释帧与空行）。"""
    out: list[dict[str, Any]] = []
    for frame in body.split("\n\n"):
        for line in frame.splitlines():
            if line.startswith("data:"):
                out.append(json.loads(line[5:].strip()))
    return out


def _run_turn(client: TestClient, session_id: str, text: str, **extra: Any) -> tuple[str, list[dict]]:
    r = client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "text": text, "client_id": "w1", **extra},
        headers=JSON,
    )
    assert r.status_code == 200, r.text
    turn_id = r.headers["x-atelier-turn-id"]
    return turn_id, _sse_events(r.text)


def _dedupe(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """前端去重口径：``turn_id + data.index``（SPEC-03 §3.3）。"""
    seen: set[tuple[str, int]] = set()
    out: list[dict[str, Any]] = []
    for ev in events:
        key = (str(ev["turn_id"]), int(ev["data"].get("index", -1)))
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return out


def _write_upload(client: TestClient, session_id: str, name: str, mime: str, body: bytes) -> dict:
    r = client.post(
        "/api/chat/upload",
        data={"session_id": session_id},
        files={"file": (name, body, mime)},
    )
    return {"status": r.status_code, "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text}


# ---------------------------------------------------------------------------
# 1. 基本流
# ---------------------------------------------------------------------------


def test_stream_emits_text_delta_then_done(client: TestClient) -> None:
    """发消息 → 收到 text_delta → done，且正文非空。"""
    sid = _new_session(client)
    turn_id, events = _run_turn(client, sid, "帮我把这条热点写成小红书图文")

    types = [e["type"] for e in events]
    assert types[0] == "thinking_start"
    assert "text_delta" in types
    assert types[-1] == "done"
    assert types.index("text_delta") < types.index("done")
    assert all(e["turn_id"] == turn_id for e in events)

    body = "".join(str(e["data"].get("text") or "") for e in events if e["type"] == "text_delta")
    done = events[-1]["data"]
    assert body.strip()
    assert done.get("text") == body
    assert done.get("interrupted") is False


def test_turn_persisted_to_jsonl(client: TestClient, atelier_root: Path) -> None:
    """每轮结束 ``var/sessions/<sid>/<turn_id>.jsonl`` 存在，且与界面一致。"""
    sid = _new_session(client)
    turn_id, events = _run_turn(client, sid, "落盘一致性检查")

    log = paths.turn_log(sid, turn_id)
    assert log.exists(), f"缺落盘文件：{paths.rel_to_root(log)}"
    lines = [ln for ln in log.read_text("utf-8").splitlines() if ln.strip()]
    assert len(lines) == len(events), "落盘条数与 SSE 事件数不一致"
    on_disk = [json.loads(ln) for ln in lines]
    assert [e["type"] for e in on_disk] == [e["type"] for e in events]
    text_stream = "".join(
        str(e["data"].get("text") or "") for e in on_disk if e["type"] == "text_delta"
    )
    assert text_stream == events[-1]["data"]["text"]


def test_stream_reattach_replays_backlog(client: TestClient) -> None:
    """``GET /turn/{id}/stream``（EventSource 用的重连端点）重放全部事件。"""
    sid = _new_session(client)
    turn_id, events = _run_turn(client, sid, "断线重连重放")

    r = client.get(f"/api/chat/turn/{turn_id}/stream")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    replayed = _sse_events(r.text)
    assert [e["type"] for e in replayed] == [e["type"] for e in events]
    assert replayed[-1]["type"] == "done"


def test_harness_error_is_traced_not_silent(client: TestClient) -> None:
    """provider 炸了 → error 事件带错误码 + done，绝不静默卡住。"""
    harness_registry.set_harness(ExplodingHarness())
    sid = _new_session(client)
    _turn_id, events = _run_turn(client, sid, "会炸的一轮")

    types = [e["type"] for e in events]
    assert "error" in types and types[-1] == "done"
    err = next(e for e in events if e["type"] == "error")["data"]
    assert err["code"] and err["message"] and err["hint"]


# ---------------------------------------------------------------------------
# 2. 断线恢复（F-B6）
# ---------------------------------------------------------------------------


def test_resume_returns_all_events(client: TestClient) -> None:
    """``GET /turn/{id}`` 拿回该轮全部事件，与流里收到的一致。"""
    sid = _new_session(client)
    turn_id, events = _run_turn(client, sid, "断线不丢")

    r = client.get(f"/api/chat/turn/{turn_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["count"] == len(events)
    assert [e["type"] for e in body["events"]] == [e["type"] for e in events]
    assert body["events"][-1]["data"]["text"] == events[-1]["data"]["text"]


def test_resume_dedup_by_index(client: TestClient) -> None:
    """事件带 0 起连续 ``index``；按 ``turn_id+index`` 去重后条数不变、不重复渲染。"""
    sid = _new_session(client)
    turn_id, _events = _run_turn(client, sid, "去重")

    first = client.get(f"/api/chat/turn/{turn_id}").json()["events"]
    second = client.get(f"/api/chat/turn/{turn_id}").json()["events"]

    indices = [e["data"]["index"] for e in first]
    assert indices == list(range(len(first))), "index 必须 0 起连续"
    # 模拟「断线重连时前端已经渲染了前 3 条，服务端又全量回了一遍」
    merged = _dedupe(first[:3] + first + second)
    assert len(merged) == len(first)
    assert [e["data"]["index"] for e in merged] == indices
    assert all(e["turn_id"] == turn_id for e in merged)


def test_resume_unknown_turn_is_404(client: TestClient) -> None:
    r = client.get("/api/chat/turn/t_doesnotexist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NotFound"
    assert r.json()["error"]["hint"]


# ---------------------------------------------------------------------------
# 3. 中断（F-B5）
# ---------------------------------------------------------------------------


async def test_interrupt_stops_within_2s(atelier_root: Path) -> None:
    """F-B5 硬指标：从调 interrupt 到收到收尾事件 ≤ 2s。"""
    db.init_db()
    harness = SlowHarness(delay=0.3, chunks=200)
    harness_registry.set_harness(harness)
    manager = mgr.get_manager()
    sid = store.create_session().id
    req = manager.build_request(session_id=sid, turn_id="t_slow", text="慢一点", profile=None)
    state = await manager.start(req, client_id="w1")
    await asyncio.sleep(0.35)  # 让它先吐一两片

    t0 = time.monotonic()
    result = await manager.interrupt(state.turn_id)
    elapsed = time.monotonic() - t0

    assert elapsed < 2.0, f"中断耗时 {elapsed:.3f}s，超出 2s 硬指标"
    assert result["ok"] and result["interrupted"] and result["was_active"]
    assert result["status"] == "interrupted"
    # 先 cancel 再 harness.interrupt 兜底（SPEC-01 §3）
    assert harness.interrupted == [state.turn_id]


async def test_interrupt_keeps_partial_text(atelier_root: Path) -> None:
    """已 yield 的 text_delta 一条不丢（用户不丢已生成内容）。"""
    db.init_db()
    harness_registry.set_harness(SlowHarness(delay=0.1, chunks=200))
    manager = mgr.get_manager()
    sid = store.create_session().id
    req = manager.build_request(session_id=sid, turn_id="t_part", text="打断我", profile=None)
    state = await manager.start(req, client_id="w1")

    seen: list[TurnEvent] = []

    async def consume() -> None:
        async for ev in manager.events(state.turn_id):
            seen.append(ev)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.35)
    await manager.interrupt(state.turn_id)
    await asyncio.wait_for(task, timeout=2.0)

    assert seen[-1].type is EventType.DONE
    assert seen[-1].data["interrupted"] is True
    partial = "".join(ev.text() for ev in seen if ev.type is EventType.TEXT_DELTA)
    assert partial, "应该有已生成内容"
    assert seen[-1].data["text"] == partial
    # 落盘里也留着，用户刷新页面还能看到
    resumed = await manager.resume(state.turn_id)
    assert resumed["status"] == "interrupted"
    assert "".join(
        str(e["data"].get("text") or "") for e in resumed["events"] if e["type"] == "text_delta"
    ) == partial


def test_interrupt_endpoint_is_idempotent(client: TestClient) -> None:
    """已结束的轮次再点停止不报错，并如实说明它已经不在跑。"""
    sid = _new_session(client)
    turn_id, _ = _run_turn(client, sid, "已经跑完了")

    r = client.post("/api/chat/interrupt", json={"turn_id": turn_id}, headers=JSON)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["was_active"] is False
    assert body["elapsed_ms"] < 2000


# ---------------------------------------------------------------------------
# 4. 问答题（F-B7）
# ---------------------------------------------------------------------------


def test_question_answered_not_repeated(client: TestClient) -> None:
    """同一 ``question_id`` 答过之后，后续轮次不再下发（**服务端**过滤）。"""
    harness = QuestionHarness("q_01")
    harness_registry.set_harness(harness)
    sid = _new_session(client)

    _turn1, events1 = _run_turn(client, sid, "第一轮")
    qs = [e for e in events1 if e["type"] == "question"]
    assert len(qs) == 1, "第一轮应该正常下发问答题"
    assert qs[0]["data"]["options"][0]["key"] == "A"

    r = client.post(
        "/api/chat/answer",
        json={"session_id": sid, "question_id": "q_01", "option_key": "A"},
        headers=JSON,
    )
    assert r.status_code == 200
    answer_events = _sse_events(r.text)
    assert not [e for e in answer_events if e["type"] == "question"], "答过之后不该再出现"
    # 选项文案作为新的 user message 继续生成
    texts = [m["text"] for m in client.get(f"/api/chat/sessions/{sid}/messages").json()["items"]]
    assert "保持这个语气，直接出终版" in texts

    turn3, events3 = _run_turn(client, sid, "第三轮，继续")
    assert not [e for e in events3 if e["type"] == "question"], "服务端必须丢弃重复提问"
    # 但 harness 侧确实又发了 → 证明是服务端过滤，不是 agent 没问
    assert any(ev.type is EventType.QUESTION for ev in harness.raw_emitted)

    resumed = client.get(f"/api/chat/turn/{turn3}").json()
    assert not [e for e in resumed["events"] if e["type"] == "question"]
    assert "q_01" in resumed["events"][0]["turn_id"] or resumed["turn_id"] == turn3

    detail = client.get(f"/api/chat/sessions/{sid}/messages").json()
    assert detail["answered_questions"] == ["q_01"]
    assert [q["question_id"] for q in detail["questions"]] == ["q_01"]
    assert detail["questions"][0]["answered"]["option_key"] == "A"
    # 内部留痕不进 UI 消息流
    assert all(m["role"] in ("user", "assistant") for m in detail["items"])


# ---------------------------------------------------------------------------
# 5. 并发防撞（F-B12）
# ---------------------------------------------------------------------------


def test_concurrent_session_returns_409(client: TestClient) -> None:
    """第二个窗口发同一会话 → 409 SessionBusy，且 detail 里带占用方。"""
    sid = _new_session(client)
    harness_registry.set_harness(HangingHarness(hang_sessions={sid}))

    first: dict[str, Any] = {}
    t = threading.Thread(
        target=lambda: first.update(
            status=client.post(
                "/api/chat/stream",
                json={"session_id": sid, "text": "窗口一", "client_id": "win-1"},
                headers=JSON,
            ).status_code
        ),
        daemon=True,
    )
    t.start()
    try:
        _wait_for(lambda: client.get("/api/chat/active").json()["turns"], lambda v: len(v) == 1)

        r = client.post(
            "/api/chat/stream",
            json={"session_id": sid, "text": "窗口二", "client_id": "win-2"},
            headers=JSON,
        )
        assert r.status_code == 409
        err = r.json()["error"]
        assert err["code"] == "SessionBusy"
        assert err["detail"]["running_client_id"] == "win-1"
        assert err["detail"]["client_id"] == "win-2"
        assert err["detail"]["same_client"] is False
        assert err["hint"]
    finally:
        turns = client.get("/api/chat/active").json()["turns"]
        for tr in turns:
            client.post("/api/chat/interrupt", json={"turn_id": tr["turn_id"]}, headers=JSON)
        t.join(timeout=10)

    assert first.get("status") == 200


def test_new_session_auto_switch_on_409(client: TestClient) -> None:
    """409 之后新建会话即可继续发（前端据此自动切会话并把消息带过去）。"""
    busy = _new_session(client)
    harness_registry.set_harness(HangingHarness(hang_sessions={busy}))

    t = threading.Thread(
        target=lambda: client.post(
            "/api/chat/stream",
            json={"session_id": busy, "text": "占着", "client_id": "win-1"},
            headers=JSON,
        ),
        daemon=True,
    )
    t.start()
    try:
        _wait_for(lambda: client.get("/api/chat/active").json()["turns"], lambda v: len(v) == 1)
        assert client.post(
            "/api/chat/stream", json={"session_id": busy, "text": "x", "client_id": "win-2"}, headers=JSON
        ).status_code == 409

        fresh = _new_session(client)
        _tid, events = _run_turn(client, fresh, "换到新会话继续", client_id="win-2")
        assert events[-1]["type"] == "done"
        titles = [s["title"] for s in client.get("/api/chat/sessions").json()["sessions"]]
        assert "换到新会话继续" in titles
    finally:
        for tr in client.get("/api/chat/active").json()["turns"]:
            client.post("/api/chat/interrupt", json={"turn_id": tr["turn_id"]}, headers=JSON)
        t.join(timeout=10)


async def test_manager_rejects_double_start(atelier_root: Path) -> None:
    """manager 层也守同一条：同 session 只允许一个活跃 turn。"""
    db.init_db()
    harness_registry.set_harness(SlowHarness(delay=0.2, chunks=50))
    manager = mgr.get_manager()
    sid = store.create_session().id
    req1 = manager.build_request(session_id=sid, turn_id="t_a", text="一", profile=None)
    await manager.start(req1, client_id="win-1")

    req2 = manager.build_request(session_id=sid, turn_id="t_b", text="二", profile=None)
    with pytest.raises(SessionBusy) as exc:
        await manager.start(req2, client_id="win-2")
    assert exc.value.http == 409
    assert exc.value.detail["running_turn_id"] == "t_a"

    await manager.interrupt("t_a")
    await manager.start(req2, client_id="win-2")  # 停了就能接着发
    await manager.interrupt("t_b")


# ---------------------------------------------------------------------------
# 6. 素材上传（F-B2 / F-B3）
# ---------------------------------------------------------------------------


def test_upload_rejects_unsupported_type(client: TestClient) -> None:
    """类型不在白名单 → 400 并说清原因。"""
    sid = _new_session(client)
    r = _write_upload(client, sid, "evil.exe", "application/octet-stream", b"MZ\x90\x00")
    assert r["status"] == 400
    err = r["body"]["error"]
    assert err["code"] == "ValidationError"
    assert "evil.exe" in err["message"]
    assert err["detail"]["reason"] == "type_not_allowed"
    assert ".pdf" in err["detail"]["allowed_suffixes"]
    assert err["hint"]


def test_upload_image_returns_structured_attachment(client: TestClient, atelier_root: Path) -> None:
    """图片上传成功 → 结构化附件，落在 ``outputs/_uploads/<sid>/``。"""
    sid = _new_session(client)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    r = _write_upload(client, sid, "截图.png", "image/png", png)
    assert r["status"] == 200
    att = r["body"]
    assert att["kind"] == "image"
    assert att["size"] == len(png)
    assert att["path"].startswith(f"outputs/_uploads/{sid}/")
    assert Path(att["absolute_path"]).is_file()

    # 索引也写了（内容库能查到这张图）
    row = db.get_conn().execute("SELECT * FROM artifacts WHERE id=?", (att["id"],)).fetchone()
    assert row is not None and row["zone"] == "素材"
    assert row["project"] == store.UPLOAD_PROJECT


def test_upload_rejects_unknown_session(client: TestClient) -> None:
    r = _write_upload(client, "s_nope", "a.png", "image/png", b"x")
    assert r["status"] == 404
    assert r["body"]["error"]["code"] == "NotFound"


async def test_attachments_are_structured_not_in_prompt(atelier_root: Path) -> None:
    """F-B3 硬规则：附件走结构化字段，**文件名不进 prompt**。"""
    db.init_db()
    sid = store.create_session().id
    att = Attachment(id="a_1", kind="image", path="outputs/_uploads/x/截图.png", name="截图.png", size=10, mime="image/png")
    manager = mgr.get_manager()
    req = manager.build_request(
        session_id=sid, turn_id="t_att", text="按这张图改一版", profile=None, attachments=[att]
    )
    assert req.prompt == "按这张图改一版"
    assert "截图.png" not in req.prompt
    assert [a.path for a in req.attachments] == ["outputs/_uploads/x/截图.png"]
    assert "先查技能库" in (req.system_suffix or "")


async def test_attachment_path_must_exist(atelier_root: Path) -> None:
    """客户端不能塞任意系统路径给 agent。"""
    db.init_db()
    sid = store.create_session().id
    store.add_message(sid, "user", "看看这个")
    from atelier.server.api import chat as chat_api

    # 绝对路径 → paths.resolve_inside 直接 PathEscapeError（也是 400，带原因）
    with pytest.raises(PathEscapeError) as exc:
        chat_api._validate_attachments(
            [chat_api.AttachmentIn(path="/etc/hosts", name="hosts", mime="text/plain")]
        )
    assert exc.value.http == 400

    # 相对路径但不存在的文件 → 400 not_found
    with pytest.raises(chat_api.UploadRejected) as exc2:
        chat_api._validate_attachments(
            [chat_api.AttachmentIn(path="outputs/_uploads/x/不存在.png", name="a.png", mime="image/png")]
        )
    assert exc2.value.detail["reason"] == "not_found"


# ---------------------------------------------------------------------------
# 7. 会话管理（F-B8）
# ---------------------------------------------------------------------------


def test_sessions_grouping_and_crud(client: TestClient) -> None:
    """新建 / 分组 / 重命名 / 归档 / 删除（需 confirm token）。"""
    a = _new_session(client, "今天写的小红书")
    b = _new_session(client, "另一条线")
    _run_turn(client, a, "第一条消息，决定标题要不要跟着变")
    assert client.get("/api/chat/sessions").json()["sessions"][0]["id"] in (a, b)

    groups = client.get("/api/chat/sessions").json()["groups"]
    assert [g["key"] for g in groups] == ["today"]
    assert len(groups[0]["items"]) == 2

    r = client.patch(f"/api/chat/sessions/{a}", json={"title": "改过的名字"}, headers=JSON)
    assert r.status_code == 200 and r.json()["session"]["title"] == "改过的名字"

    r = client.post(f"/api/chat/sessions/{b}/archive", headers=JSON)
    assert r.status_code == 200 and r.json()["archived"] is True
    groups = client.get("/api/chat/sessions").json()["groups"]
    assert {g["key"] for g in groups} == {"today", "archived"}
    assert client.get("/api/chat/sessions?include_archived=false").json()["count"] == 1

    # 删会话必须带 confirm token（SPEC-01 §8.1）
    # 不带 confirm token 一律拒绝（错误体给出「先申请 token」的下一步）
    no_token = client.delete(f"/api/chat/sessions/{b}", headers=JSON)
    assert no_token.status_code == 422
    assert no_token.json()["error"]["code"] == "ValidationError"
    assert "confirm" in no_token.json()["error"]["message"]
    assert no_token.json()["error"]["hint"]
    tok = client.post("/api/chat/confirm-token", json={"action": "delete-session", "id": b}, headers=JSON).json()
    bad = client.delete(f"/api/chat/sessions/{b}?confirm=1.deadbeef", headers=JSON)
    assert bad.status_code == 422 and "confirm" in bad.json()["error"]["message"]

    ok = client.delete(f"/api/chat/sessions/{b}?confirm={tok['token']}", headers=JSON)
    assert ok.status_code == 200 and ok.json()["removed"] is True
    assert client.get(f"/api/chat/sessions/{b}/messages").status_code == 404


def test_session_title_never_uses_file_name(client: TestClient) -> None:
    """F-B3：标题取用户输入的前 20 字，不取文件名。"""
    sid = _new_session(client)
    _write_upload(client, sid, "灵感图.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"0" * 16)
    att = client.get("/api/chat/active")  # 顺带确认 active 端点不报错
    assert att.status_code == 200

    msgs = client.get(f"/api/chat/sessions/{sid}/messages").json()["items"]
    assert msgs == []
    s = client.get("/api/chat/sessions").json()["sessions"][0]
    assert s["title"] == "新会话"  # 没发消息就不该有标题
    assert "灵感图" not in json.dumps(client.get("/api/chat/sessions").json(), ensure_ascii=False)


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _wait_for(getter: Any, ok: Any, *, timeout: float = 5.0, step: float = 0.05) -> Any:
    """轮询到条件满足为止（只用于测试编排，不是生产路径）。"""
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = getter()
        if ok(last):
            return last
        time.sleep(step)
    raise AssertionError(f"等待超时，最后一次取值：{last}")


def test_models_untouched_by_chat_domain() -> None:
    """守住 F-B3 的另一半：Attachment 模型的 path 语义仍是「相对 outputs/ 的 posix 路径」。"""
    a = Attachment(id="a", kind="image", path="outputs/_uploads/s/a.png", name="a.png", size=1, mime="image/png")
    assert isinstance(models.Attachment.model_validate(a.model_dump(mode="json")), Attachment)
