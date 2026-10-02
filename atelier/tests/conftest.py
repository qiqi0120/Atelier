"""pytest 公共夹具。

**最重要的一条**：所有测试都跑在临时根目录下（``atelier_root`` 夹具），
绝不碰真实的 ``Atelier/outputs``、``Atelier/var``、``Atelier/profiles``。
没有这个夹具的测试不允许存在——它会把开发者本机的产物目录写脏。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from atelier.server import paths
from atelier.server.config import reload_settings
from atelier.server.core import db


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
