"""SPEC-03 §3 · ★ 活跃 turn 管理、并发锁、中断、断线恢复。

这一层是本域的重心，四条硬要求都在这里落地：

1. **同一 session 同时只允许一个活跃 turn**（PRD F-B12）。占用登记在
   :attr:`TurnManager._active`，冲突抛 :class:`SessionBusy`（HTTP 409）。
   409 必须**在开流之前**抛出——所以 ``POST /api/chat/stream`` 的 409 是 JSON
   错误体，不是 SSE 里的一条 error 事件。
2. **2s 内停止**（PRD F-B5）。顺序固定：先 :meth:`asyncio.Task.cancel`，
   最多等 0.6s 让 task 自己收尾；还没收尾就由 manager 直接补一条
   ``done{interrupted:true, partial:true}`` 推给订阅者，界面立刻停。
   再调 ``harness.interrupt()`` 兜底（真 provider 侧可能还有连接要断）。
3. **断线不丢**（PRD F-B6）。每个事件实时落两份盘：
   ``<turn_id>.jsonl``（harness 层写的原始事件，SPEC-01 §3）与
   ``<turn_id>.stream.jsonl``（本层写的**实际下发**事件，带 ``index``）。
   resume 优先读后者——因为被 F-B7 过滤掉的重复问答题不会出现在那里，
   断线重连后也**不会**重新弹出来。
4. **问答题不重复**（PRD F-B7）。会话级 ``answered_questions`` 内存索引 +
   落库留痕；agent 重复发同一 ``question_id`` 时直接丢弃，不下发、不落盘。

**事件序号**：每个下发事件都带 ``data.index``（从 0 递增）与 ``data.at``
（epoch 秒）。前端按 ``turn_id + index`` 去重（SPEC-03 §3.3）。

**不轮询文件**：SSE 走内存队列（:attr:`TurnState.subscribers`）实时推送，
落盘只是给「重连后补齐」用的真相源。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import paths
from ..config import get_settings
from ..core import models
from ..errors import AtelierError, HarnessTimeout, SessionBusy
from ..harness.base import EventType, TurnEvent, TurnRequest, read_turn_events
from ..harness.registry import get_harness
from . import store

log = logging.getLogger("atelier.sessions.manager")

__all__ = [
    "CLOSING_EVENTS",
    "PER_ROUND_REMINDER",
    "STATUS_DONE",
    "STATUS_ERROR",
    "STATUS_INTERRUPTED",
    "STATUS_RUNNING",
    "TERMINAL_EVENTS",
    "TurnManager",
    "TurnState",
    "get_manager",
    "load_profile",
    "profile_prefix",
    "reset_manager",
    "stream_log_path",
]

#: 出现即本轮结束的终态事件（SSE 读到就收流）
TERMINAL_EVENTS: frozenset[EventType] = frozenset({EventType.DONE, EventType.ERROR})

#: **只有** done 才真正给这一轮收尾（error 之后还会跟一条 done，
#: 两帧都给前端才能既看到原因、又确定生成结束了）
CLOSING_EVENTS: frozenset[EventType] = frozenset({EventType.DONE})

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_INTERRUPTED = "interrupted"
STATUS_ERROR = "error"

#: cancel 之后最多等 task 自行收尾的时间（留足余量给 2s 硬指标）
CANCEL_GRACE_SECONDS = 0.6

#: SPEC-02 §4「每轮重申流程提醒」，对抗长对话指令衰减
PER_ROUND_REMINDER = (
    "【流程提醒】动手前先查技能库（skills/ 目录），有现成技能就用，不要从零手搓。\n"
    "产出落盘前必须调用 atelier_gate_run 跑门禁；图片等产物用 atelier_artifact_write 写入。"
)

#: 本层事件落盘的旁路文件名后缀（区别于 harness 写的原始 jsonl）
STREAM_LOG_SUFFIX = ".stream.jsonl"


def stream_log_path(session_id: str, turn_id: str) -> Path:
    """``var/sessions/<sid>/<turn_id>.stream.jsonl``（本层「实际下发事件」落盘）。"""
    paths.validate_id(session_id, "session_id")
    paths.validate_id(turn_id, "turn_id")
    return paths.resolve_inside(paths.session_dir(session_id), f"{turn_id}{STREAM_LOG_SUFFIX}")


# ---------------------------------------------------------------------------
# 画像注入（SPEC-02 §4）
# ---------------------------------------------------------------------------


def load_profile(profile_id: str | None) -> models.Profile | None:
    """按 id 取画像。

    优先走画像域的 store（``atelier.server.profile``）；该域尚未落地时退回直接读
    ``profiles`` 表——表结构属 SPEC-01 §7 冻结契约，模型是共享的
    ``core.models.Profile``，所以这个退路不会引入新的耦合面。
    """
    if not profile_id:
        return None
    try:
        from ..profile import store as profile_store  # type: ignore[import-not-found]

        p = profile_store.get_profile(profile_id)
        if p is not None:
            return p
    except Exception:
        log.debug("profile store 不可用，回退直读 profiles 表：%s", profile_id, exc_info=True)

    from ..core import db

    row = db.get_conn().execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    if row is None:
        return None
    mem_rows = db.get_conn().execute(
        "SELECT * FROM memories WHERE profile_id=? ORDER BY created_at", (profile_id,)
    ).fetchall()
    return models.Profile(
        id=row["id"],
        name=row["name"],
        platforms=db.loads(row["platforms"], []) or [],
        identity=row["identity"] or "",
        style=row["style"] or "",
        audience=row["audience"] or "",
        platform_rules=row["platform_rules"] or "",
        preferences=row["preferences"] or "",
        memories=[
            models.Memory(
                id=m["id"],
                text=m["text"],
                source=m["source"] or "手动",
                created_at=m["created_at"],
                adopted=bool(m["adopted"]),
            )
            for m in mem_rows
        ],
        general_mode=bool(row["general_mode"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def profile_prefix(profile: models.Profile | None) -> str:
    """画像 → 注入前缀（SPEC-02 §4 的 ``build_profile_prefix``）。

    画像域落地后用它的实现；没有就用本文件里逐字等价的兜底版，格式与 spec 一致，
    保证「画像不落全局文件、每轮现拼」这条硬约束始终成立。
    """
    if profile is None or profile.general_mode:
        return ""
    try:
        from ..profile.prompt import build_profile_prefix  # type: ignore[import-not-found]

        return str(build_profile_prefix(profile))
    except Exception:
        log.debug("profile.prompt 不可用，用本域兜底实现", exc_info=True)
    memories = "\n".join(f"- {m.text}" for m in profile.memories) or "（暂无）"
    return (
        "<account_profile>\n"
        f"## 定位\n{profile.identity}\n\n"
        f"## 风格\n{profile.style}\n\n"
        f"## 受众\n{profile.audience}\n\n"
        f"## 平台约束\n{profile.platform_rules}\n\n"
        f"## 偏好红线（禁止违反）\n{profile.preferences}\n\n"
        f"## 长期记忆\n{memories}\n"
        "</account_profile>"
    )


# ---------------------------------------------------------------------------
# Turn 状态
# ---------------------------------------------------------------------------


@dataclass
class TurnState:
    """一轮生成的服务端状态。**只放内存**：终态一到就从注册表摘掉，
    之后的一切从落盘回答（这样换事件循环/重启后不会留下绑死旧 loop 的队列）。"""

    turn_id: str
    session_id: str
    client_id: str
    profile_id: str | None = None
    project: str | None = None
    task: asyncio.Task[None] | None = None
    events: list[TurnEvent] = field(default_factory=list)
    subscribers: set[asyncio.Queue[TurnEvent]] = field(default_factory=set)
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    status: str = STATUS_RUNNING
    closed: bool = False
    interrupted: bool = False
    text: str = ""
    thinking: str = ""
    gate: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    questions: dict[str, dict[str, Any]] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)

    def snapshot(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "client_id": self.client_id,
            "status": self.status,
            "interrupted": self.interrupted,
            "event_count": len(self.events),
            "chars": len(self.text),
            "elapsed_ms": int((time.monotonic() - self.started_at) * 1000),
            "artifacts": list(self.artifacts),
            "questions": list(self.questions),
        }


# ---------------------------------------------------------------------------
# manager
# ---------------------------------------------------------------------------


class TurnManager:
    """进程内 turn 注册表 + 事件总线。"""

    def __init__(self, *, timeout: float | None = None) -> None:
        self._turns: dict[str, TurnState] = {}
        self._active: dict[str, str] = {}  # session_id → turn_id
        self._answered: dict[str, set[str]] = {}  # session_id → 已答 question_id
        self._questions: dict[str, dict[str, dict[str, Any]]] = {}  # session_id → qid → question data
        self._status: dict[str, str] = {}  # turn_id → 终态（给 /turn/{id} 用）
        # turn_id → session_id 常驻索引：轮次结束后要从落盘找旁路 jsonl，
        # 而桩 harness 可能一份原始 jsonl 都没写，所以映射不能随状态一起摘掉。
        self._owner: dict[str, str] = {}
        self._timeout = timeout

    # -- 基础查询 -----------------------------------------------------------

    @property
    def timeout(self) -> float:
        return float(self._timeout if self._timeout is not None else get_settings().harness_timeout)

    def get(self, turn_id: str) -> TurnState | None:
        return self._turns.get(turn_id)

    def active_turn(self, session_id: str) -> TurnState | None:
        turn_id = self._active.get(session_id)
        return self._turns.get(turn_id) if turn_id else None

    def active_turns(self) -> list[dict[str, Any]]:
        return [s.snapshot() for s in self._turns.values()]

    def status(self, turn_id: str) -> str | None:
        state = self._turns.get(turn_id)
        if state is not None:
            return state.status
        return self._status.get(turn_id)

    def session_id_of(self, turn_id: str) -> str | None:
        state = self._turns.get(turn_id)
        if state is not None:
            return state.session_id
        owner = self._owner.get(turn_id)
        if owner:
            return owner
        for p in paths.turn_log_paths(turn_id):
            return p.parent.name
        return None

    def answered(self, session_id: str) -> set[str]:
        """会话内已答问题（内存 + 落库重建）。"""
        cached = self._answered.get(session_id)
        if cached is None:
            cached = store.answered_questions(session_id)
            self._answered[session_id] = cached
        return cached

    def question(self, session_id: str, question_id: str) -> dict[str, Any] | None:
        return self._questions.get(session_id, {}).get(question_id)

    def option_label(self, session_id: str, question_id: str, option_key: str) -> str:
        """``option_key`` → 选项文案（agent 侧留痕优先，其次落库重建）。"""
        q = self._questions.get(session_id, {}).get(question_id)
        if not q:
            for row in store.list_questions(session_id):
                if row.get("question_id") == question_id:
                    q = row
                    break
        for opt in (q or {}).get("options") or []:
            if str(opt.get("key")) == str(option_key):
                return str(opt.get("label") or opt.get("key"))
        return str(option_key)

    # -- 提问过滤（F-B7） ---------------------------------------------------

    def _is_duplicate_question(self, session_id: str, turn_id: str, ev: TurnEvent) -> bool:
        qid = str(ev.data.get("question_id") or "")
        if not qid:
            # 没带 id 的问题按「本轮第几个」兜底，避免全部被当成同一道题
            qid = f"{turn_id}:q{len(self._questions.get(session_id, {}))}"
            ev.data["question_id"] = qid
        if qid in self.answered(session_id):
            log.info("重复问答题已丢弃（服务端过滤，F-B7）：session=%s question_id=%s", session_id, qid)
            return True
        return False

    def note_question(self, session_id: str, turn_id: str, ev: TurnEvent) -> None:
        """记下问题本体（供 ``/answer`` 解析选项文案 + 刷新后重建卡片）。"""
        qid = str(ev.data.get("question_id") or "")
        data = {
            "question_id": qid,
            "turn_id": turn_id,
            "text": str(ev.data.get("text") or ""),
            "options": list(ev.data.get("options") or []),
            "multiple": bool(ev.data.get("multiple")),
        }
        self._questions.setdefault(session_id, {})[qid] = data
        with contextlib.suppress(Exception):
            store.mark_question(session_id, qid, data)

    def mark_answered(self, session_id: str, question_id: str, option_key: str, label: str) -> dict[str, str]:
        """记录答案并立刻进内存集合（后续轮次同 id 直接丢）。"""
        self.answered(session_id).add(question_id)
        q = self._questions.setdefault(session_id, {}).get(question_id)
        if q is not None:
            q["answered"] = {"option_key": option_key, "label": label}
        return store.mark_answered(session_id, question_id, option_key, label)

    # -- 组装请求 -----------------------------------------------------------

    def build_request(
        self,
        *,
        session_id: str,
        turn_id: str,
        text: str,
        profile: models.Profile | None,
        attachments: list[models.Attachment] | None = None,
        project: str | None = None,
        system_suffix: str | None = None,
    ) -> TurnRequest:
        """组装 :class:`TurnRequest`。

        **F-B3 硬规则**：`prompt` 只放用户实际输入的文字。附件走
        ``TurnRequest.attachments`` 结构化字段（含真实路径，agent 自己读），
        绝不把文件名拼进 prompt——消息气泡也只显示这段文字。
        画像也不拼进 prompt：它进 ``profile`` 字段由 harness 拼成 system_prompt
        （SPEC-01 §4：不落全局文件，并发画像互不污染）。
        """
        suffix_parts = [PER_ROUND_REMINDER]
        if system_suffix:
            suffix_parts.append(system_suffix.strip())
        return TurnRequest(
            session_id=session_id,
            turn_id=turn_id,
            prompt=text or "",
            profile=profile,
            attachments=list(attachments or []),
            system_suffix="\n".join(suffix_parts),
            project=project,
        )

    # -- 启动 ---------------------------------------------------------------

    async def start(
        self,
        req: TurnRequest,
        *,
        client_id: str = "anonymous",
        profile_id: str | None = None,
    ) -> TurnState:
        """登记并开跑一轮。占用冲突抛 :class:`SessionBusy`（409）。"""
        session_id = req.session_id
        busy = self.active_turn(session_id)
        if busy is not None:
            raise SessionBusy(
                "该会话正在被另一个窗口生成",
                detail={
                    "session_id": session_id,
                    "running_turn_id": busy.turn_id,
                    "running_client_id": busy.client_id,
                    "client_id": client_id,
                    "same_client": busy.client_id == client_id,
                },
            )
        state = TurnState(
            turn_id=req.turn_id,
            session_id=session_id,
            client_id=client_id,
            profile_id=profile_id,
            project=req.project,
        )
        self._turns[req.turn_id] = state
        self._active[session_id] = req.turn_id
        self._owner[req.turn_id] = session_id
        if len(self._owner) > 2000:  # 本地工具，够用即可；防无限增长
            for stale in list(self._owner)[:1000]:
                if stale not in self._status:
                    self._owner.pop(stale, None)
        self._answered.pop(session_id, None)  # 强制从落库重建，保证跨重启一致
        state.task = asyncio.create_task(self._run(state, req), name=f"turn-{req.turn_id}")
        return state

    # -- 事件管线 -----------------------------------------------------------

    def _emit(self, state: TurnState, ev: TurnEvent) -> TurnEvent | None:
        """给事件编号 → 落盘 → 累积 → 推给订阅者 → 终态收尾。

        返回 ``None`` 表示被丢弃（重复问答题 / 本轮已关闭）。
        """
        if state.closed:
            return None
        if ev.type is EventType.QUESTION and self._is_duplicate_question(
            state.session_id, state.turn_id, ev
        ):
            return None

        ev.turn_id = state.turn_id
        ev.data["index"] = len(state.events)
        ev.data.setdefault("at", round(time.time(), 3))
        state.events.append(ev)
        self._write(state, ev)
        self._accumulate(state, ev)

        if ev.type in CLOSING_EVENTS:
            state.closed = True
            interrupted = bool(ev.data.get("interrupted")) or state.interrupted
            state.interrupted = interrupted
            state.status = (
                STATUS_INTERRUPTED
                if interrupted
                else (STATUS_ERROR if ev.data.get("failed") else STATUS_DONE)
            )
            self._persist_assistant(state)
            self._release(state)

        for q in list(state.subscribers):
            with contextlib.suppress(asyncio.QueueFull):  # 队列无界，这个分支只是防御
                q.put_nowait(ev)
        return ev

    def _write(self, state: TurnState, ev: TurnEvent) -> None:
        """实时 append 到旁路 jsonl（断线恢复「实际下发过什么」的真相源）。"""
        try:
            p = stream_log_path(state.session_id, state.turn_id)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")
        except OSError:  # 落盘失败不能把生成也拖垮（doctor 会暴露）
            log.warning("事件落盘失败：session=%s turn=%s", state.session_id, state.turn_id, exc_info=True)

    def _accumulate(self, state: TurnState, ev: TurnEvent) -> None:
        """按事件累积状态 + 写 messages / artifacts 表。"""
        if ev.type is EventType.TEXT_DELTA:
            state.text += ev.text()
        elif ev.type is EventType.THINKING_DELTA:
            state.thinking += ev.text()
        elif ev.type is EventType.THINKING_START:
            state.thinking = ""
        elif ev.type is EventType.QUESTION:
            self.note_question(state.session_id, state.turn_id, ev)
        elif ev.type is EventType.GATE_RESULT:
            state.gate = _normalize_gate(ev.data)
        elif ev.type is EventType.ARTIFACT:
            for item in _artifact_items(ev.data):
                row = self._record_artifact(state, item)
                if row is not None:
                    state.artifacts.append(row)

    def _record_artifact(self, state: TurnState, item: dict[str, Any]) -> dict[str, Any] | None:
        rel = str(item.get("path") or item.get("rel_path") or "").strip()
        if not rel:
            return None
        try:
            return store.record_artifact(
                session_id=state.session_id,
                turn_id=state.turn_id,
                rel_path=rel,
                kind=str(item.get("kind") or "doc"),
                size=int(item.get("size") or 0),
                mime=str(item.get("mime") or "application/octet-stream"),
                project=str(item.get("project") or state.project or "default"),
                zone=str(item.get("zone") or "成品"),
            )
        except Exception:
            log.warning("产物索引写库失败：%s", rel, exc_info=True)
            return None

    def _persist_assistant(self, state: TurnState) -> None:
        """DONE 时把这一轮的正文 + 门禁结果写成一条 assistant 消息。"""
        if not (state.text.strip() or state.gate or state.artifacts):
            return
        try:
            store.add_message(
                state.session_id,
                "assistant",
                state.text,
                turn_id=state.turn_id,
                gate_report=state.gate,
            )
            store.update_session(state.session_id, last_turn_id=state.turn_id)
        except Exception:
            log.warning("assistant 消息落库失败：turn=%s", state.turn_id, exc_info=True)

    def _release(self, state: TurnState) -> None:
        """摘掉注册表占用 + 置终态。订阅者仍持有 state 引用，能收到收尾事件。"""
        if self._active.get(state.session_id) == state.turn_id:
            self._active.pop(state.session_id, None)
        if self._turns.get(state.turn_id) is state:
            self._turns.pop(state.turn_id, None)
        self._status[state.turn_id] = state.status
        state.finished.set()

    # -- 主循环 -------------------------------------------------------------

    async def _run(self, state: TurnState, req: TurnRequest) -> None:
        harness = get_harness()
        it: Any = None
        try:
            it = harness.stream(req).__aiter__()
        except Exception as exc:  # noqa: BLE001 - stream() 本身抛错（同步部分）
            self._fail(state, exc)
            return

        while True:
            if time.monotonic() - state.started_at > self.timeout:
                self._error_event(
                    state,
                    HarnessTimeout(
                        f"AI 生成超时（> {int(self.timeout)}s）",
                        detail={"turn_id": state.turn_id, "partial_chars": len(state.text)},
                    ),
                )
                return
            try:
                ev = await asyncio.wait_for(it.__anext__(), timeout=self.timeout)
            except StopAsyncIteration:
                break
            except TimeoutError:
                self._error_event(
                    state,
                    HarnessTimeout(
                        f"AI 生成超时（> {int(self.timeout)}s）",
                        detail={"turn_id": state.turn_id, "partial_chars": len(state.text)},
                    ),
                )
                return
            except asyncio.CancelledError:
                # 中断：已 yield 的 text_delta 都保留，补一条 done 收尾（PRD F-B5）
                state.interrupted = True
                self._emit(
                    state,
                    TurnEvent(
                        EventType.DONE,
                        state.turn_id,
                        {
                            "interrupted": True,
                            "partial": True,
                            "text": state.text,
                            "by": "cancel",
                            "chars": len(state.text),
                        },
                    ),
                )
                return
            except AtelierError as exc:
                self._fail(state, exc)
                return
            except Exception as exc:  # noqa: BLE001 - provider 崩了也要留痕（原则四）
                self._fail(state, exc)
                return
            if self._emit(state, ev) is None and state.closed:
                return
            if state.closed:
                return

        # 正常结束但 provider 没发终态：补一条 done，保证前端不卡在「生成中」
        self._emit(
            state,
            TurnEvent(
                EventType.DONE,
                state.turn_id,
                {"text": state.text, "interrupted": state.interrupted, "provider": getattr(harness, "name", "?")},
            ),
        )

    def _fail(self, state: TurnState, exc: BaseException) -> None:
        if isinstance(exc, AtelierError):
            err = exc.to_dict()
        else:
            err = {
                "code": "HarnessError",
                "message": f"AI 运行时异常：{type(exc).__name__}",
                "detail": {"type": type(exc).__name__},
                "hint": "跑 `atelier doctor` 看环境诊断；已生成部分不会丢",
            }
            log.exception("turn 失败：turn=%s", state.turn_id)
        self._emit(state, TurnEvent(EventType.ERROR, state.turn_id, {**err, "text": state.text}))
        self._emit(
            state,
            TurnEvent(
                EventType.DONE,
                state.turn_id,
                {"text": state.text, "interrupted": state.interrupted, "failed": True},
            ),
        )

    def _error_event(self, state: TurnState, exc: AtelierError) -> None:
        self._emit(state, TurnEvent(EventType.ERROR, state.turn_id, {**exc.to_dict(), "text": state.text}))
        self._emit(
            state,
            TurnEvent(
                EventType.DONE,
                state.turn_id,
                {"text": state.text, "interrupted": state.interrupted, "failed": True},
            ),
        )

    # -- 订阅（SSE 的数据源，内存队列实时推，不是轮询文件） ------------------

    async def events(self, turn_id: str) -> AsyncIterator[TurnEvent]:
        """该轮的事件流：先补历史 backlog，再接实时队列。

        本轮还在跑 → 内存队列接着推（重连场景）。
        本轮已结束 / 不在内存 → 从落盘重放（断线 10 秒后恢复的路径）。
        """
        state = self._turns.get(turn_id)
        if state is not None and not state.closed:
            queue: asyncio.Queue[TurnEvent] = asyncio.Queue()
            state.subscribers.add(queue)
            try:
                for ev in list(state.events):
                    yield ev
                while True:
                    ev = await queue.get()
                    yield ev
                    if ev.type in TERMINAL_EVENTS:
                        return
            finally:
                state.subscribers.discard(queue)
        for ev in await self.resume_events(turn_id):
            yield ev

    # -- 中断（2s 硬指标） --------------------------------------------------

    async def interrupt(self, turn_id: str) -> dict[str, Any]:
        """中断一轮。**先 cancel，再 harness.interrupt 兜底**（SPEC-01 §3）。"""
        state = self._turns.get(turn_id)
        if state is None:
            with contextlib.suppress(Exception):
                await get_harness().interrupt(turn_id)
            return {
                "ok": True,
                "turn_id": turn_id,
                "was_active": False,
                "interrupted": True,
                "status": self._status.get(turn_id, STATUS_DONE),
                "note": "本轮已结束（可能已断线），只做了一次兜底通知",
            }

        state.interrupted = True
        task = state.task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(
                    asyncio.shield(state.finished.wait()), timeout=CANCEL_GRACE_SECONDS
                )
        if not state.closed:
            # task 没在宽限期内收尾（provider 吞了取消）→ manager 直接补收尾事件，
            # 界面立刻停，绝不等到超时。
            self._emit(
                state,
                TurnEvent(
                    EventType.DONE,
                    turn_id,
                    {
                        "interrupted": True,
                        "partial": True,
                        "text": state.text,
                        "by": "manager",
                        "chars": len(state.text),
                    },
                ),
            )
        with contextlib.suppress(Exception):
            await get_harness().interrupt(turn_id)
        return {
            "ok": True,
            "turn_id": turn_id,
            "was_active": True,
            "interrupted": True,
            "status": state.status,
            "partial_chars": len(state.text),
            "event_count": len(state.events),
        }

    # -- 断线恢复 -----------------------------------------------------------

    def _read_log(self, path: Path) -> list[TurnEvent]:
        if not path.exists():
            return []
        out: list[TurnEvent] = []
        for line in path.read_text("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(TurnEvent.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue  # 落盘可能正写到最后一行；坏行跳过，不让恢复链路整条挂掉
        return out

    async def resume_events(self, turn_id: str) -> list[TurnEvent]:
        """该轮**已下发过**的全部事件，按 ``index`` 排序。

        优先读旁路 ``<turn>.stream.jsonl``（带 index、且不含被过滤掉的重复问题）；
        旁路不在（进程重启前的老轮次）时退回 harness 的原始 ``<turn>.jsonl``，
        按出现顺序补 ``index``——顺序稳定，所以去重依然成立。
        """
        state = self._turns.get(turn_id)
        if state is not None:
            events = list(state.events)
            if events or state.closed:
                return events

        session_id = self.session_id_of(turn_id)
        if session_id:
            events = self._read_log(stream_log_path(session_id, turn_id))
            if events:
                return _reindex(events)
        events = read_turn_events(turn_id)  # 兜底：按 turn_id 全盘找
        return _reindex(events) if events else []

    async def resume(self, turn_id: str) -> dict[str, Any]:
        """``GET /api/chat/turn/{id}`` 的响应体：``{events, status}``（SPEC-03 §3.3）。"""
        paths.validate_id(turn_id, "turn_id")
        events = await self.resume_events(turn_id)
        status = self.status(turn_id) or _status_from_events(events)
        return {
            "turn_id": turn_id,
            "status": status,
            "count": len(events),
            "last_index": (events[-1].data.get("index") if events else None),
            "events": [e.to_dict() for e in events],
        }


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _reindex(events: list[TurnEvent]) -> list[TurnEvent]:
    """按 ``index`` 排序并补齐缺失的序号（兜底落盘路径用）。"""
    for i, ev in enumerate(events):
        ev.data.setdefault("index", i)
    events.sort(key=lambda e: int(e.data.get("index", 0)))
    return events


def _status_from_events(events: list[TurnEvent]) -> str:
    if not events:
        return STATUS_DONE
    last = events[-1]
    if last.type is EventType.ERROR or last.data.get("failed"):
        return STATUS_ERROR
    if last.data.get("interrupted"):
        return STATUS_INTERRUPTED
    return STATUS_DONE


def _normalize_gate(data: dict[str, Any]) -> dict[str, Any]:
    """``gate_result`` 事件 → ``{items, blocked}``（两种形状都吃）。"""
    report = data.get("report") if isinstance(data.get("report"), dict) else data
    items = list(report.get("items") or [])
    blocked = bool(report.get("blocked")) or any(
        str(i.get("severity", "")).lower() == "block" and not i.get("passed", False) for i in items
    )
    return {"items": items, "blocked": blocked}


def _artifact_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """``artifact`` 事件 → 产物条目列表（吃 ``path`` 与 ``paths`` 两种形状）。"""
    paths_list = data.get("paths")
    if isinstance(paths_list, list) and paths_list:
        common = {k: v for k, v in data.items() if k not in ("path", "rel_path", "paths")}
        return [{**common, "path": p} for p in paths_list]
    rel = data.get("path") or data.get("rel_path")
    return [{**data, "path": rel}] if rel else []


# ---------------------------------------------------------------------------
# 进程内单例
# ---------------------------------------------------------------------------

_manager = TurnManager()


def get_manager() -> TurnManager:
    """业务层统一从这里取（与 ``harness.registry.get_harness`` 同风格）。"""
    return _manager


def reset_manager() -> None:
    """换测试根 / 重启时清空注册表。"""
    global _manager
    _manager = TurnManager()
