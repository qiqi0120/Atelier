"""Harness 层契约（**SDK-free**）。

这里只导出 :mod:`atelier.server.harness.base` 的类型。**provider 实现不在这里
import**——``claude_sdk`` / provider 注册表都靠惰性导入，理由见 registry.py。
"""

from __future__ import annotations

from .base import (
    EventType,
    Harness,
    HealthReport,
    MockHarness,
    TurnEvent,
    TurnRecorder,
    TurnRequest,
    read_turn_events,
)

__all__ = [
    "EventType",
    "Harness",
    "HealthReport",
    "MockHarness",
    "TurnEvent",
    "TurnRecorder",
    "TurnRequest",
    "read_turn_events",
]
