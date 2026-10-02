"""pytest 公共夹具。

**最重要的一条**：所有测试都跑在临时根目录下（``atelier_root`` 夹具），
绝不碰真实的 ``Atelier/outputs``、``Atelier/var``、``Atelier/profiles``。
没有这个夹具的测试不允许存在——它会把开发者本机的产物目录写脏。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from atelier.server import paths
from atelier.server.config import reload_settings
from atelier.server.core import db
from atelier.server.harness import registry as harness_registry
from atelier.server.harness.base import EventType, HealthReport, TurnEvent, TurnRequest


class ScriptedHarness:
    """按队列吐文本的假 harness（M2 起供 topics / calendar 等域共用）。

    记录 TurnRequest，供断言画像注入与 prompt 拼装。真实模型不可测，
    mock 的写死文本又过不了结构化约定，所以用可控输出的假 harness
    断言「域服务对 harness 的用法」与「解析/门禁/落库」。
    """

    name = "scripted"

    def __init__(self, outputs: list[str] | None = None) -> None:
        self.outputs: list[str] = list(outputs or [])
        self.requests: list[TurnRequest] = []

    async def stream(self, req: TurnRequest) -> AsyncIterator[TurnEvent]:
        self.requests.append(req)
        text = self.outputs.pop(0) if self.outputs else ""
        yield TurnEvent(EventType.TEXT_DELTA, req.turn_id, {"text": text})
        yield TurnEvent(EventType.DONE, req.turn_id, {"text": text, "provider": self.name})

    async def interrupt(self, turn_id: str) -> None:  # pragma: no cover - 本批用不到
        return None

    async def resume(self, turn_id: str) -> list[TurnEvent]:  # pragma: no cover
        return []

    async def health(self) -> HealthReport:
        return HealthReport(name=self.name, ok=True)

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake() -> Iterator[ScriptedHarness]:
    """注册脚本化假 harness，用完卸载（AI 任务域测试共用）。"""
    h = ScriptedHarness()
    harness_registry.set_harness(h)
    yield h
    harness_registry.set_harness(None)


@pytest.fixture
def atelier_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """把整个 Atelier 根切到 tmp_path，并刷新 paths / settings / db 连接。"""
    root = tmp_path / "atelier-root"
    root.mkdir()
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    monkeypatch.setenv("ATELIER_MOCK", "1")
    paths.configure(str(root))
    reload_settings()
    db.reset_conn()
    yield root
    db.reset_conn()
    monkeypatch.delenv("ATELIER_ROOT", raising=False)
    paths.configure()  # 还原成默认根
    reload_settings()


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """清掉可能影响 doctor / harness 判断的外部变量。"""
    for name in (
        "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ATELIER_MASTER_KEY",
        "MINIMAX_API_KEY", "TTS_API_KEY", "XHS_COOKIE", "DY_COOKIE", "GZH_COOKIE",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture
def in_tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """切到空目录（测路径解析时避免碰真实仓库）。"""
    monkeypatch.chdir(tmp_path)
    yield tmp_path


@pytest.fixture
def anyio_backend() -> str:  # pragma: no cover - 兼容以防有人用 anyio
    return "asyncio"


def pytest_configure(config: pytest.Config) -> None:
    # 明确警告：不要在真实根目录里跑测试
    os.environ.setdefault("ATELIER_TESTING", "1")
