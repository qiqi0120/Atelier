"""Harness provider 注册表（SPEC-01 §4「未来可换 provider」）。

选择逻辑：

1. ``ATELIER_MOCK=1`` → :class:`MockHarness`（无 API key 也能跑通全部测试与 E2E）
2. 否则按 ``ATELIER_HARNESS``（默认 ``claude_sdk``）惰性 import 对应实现

**惰性 import 的原因**（也是分层纪律的一部分）：

- :class:`MockHarness` 来自 :mod:`atelier.server.harness.base`，那个文件禁止 import
  SDK 包；如果这里在模块顶层 import claude_sdk，那么任何用到
  Mock 的代码路径都会被 SDK 的导入链拖住（SDK 装不上 / 版本不兼容 → 整条路挂掉）。
- 同理 ``claude_sdk`` 只有在真的要用它时才 import。

业务层（api / cli）只调 :func:`get_harness`，不 import 任何具体实现。
"""

from __future__ import annotations

from typing import Any

from ..config import get_settings
from .base import Harness, MockHarness

__all__ = [
    "PROVIDERS",
    "available_providers",
    "create_harness",
    "current_harness",
    "get_harness",
    "reset_harness",
    "set_harness",
]

#: provider 名 → ``module:ClassName``（惰性加载，故存字符串）
PROVIDERS: dict[str, str] = {
    "claude_sdk": "atelier.server.harness.claude_sdk:ClaudeSDKHarness",
    "mock": "atelier.server.harness.base:MockHarness",
}

_instance: Any = None


def available_providers() -> list[str]:
    return sorted(PROVIDERS)


def create_harness(name: str | None = None, **kwargs: Any) -> Harness:
    """按名字造一个 provider 实例。未知名字抛 ``HarnessError``（不留裸 ValueError）。"""
    from ..errors import HarnessError

    settings = get_settings()
    wanted = name or ("mock" if settings.mock else settings.harness_name)
    if wanted == "mock":
        return MockHarness(**kwargs)  # type: ignore[return-value]

    target = PROVIDERS.get(wanted)
    if target is None:
        raise HarnessError(
            f"没有这个 harness provider：{wanted}",
            detail={"available": available_providers()},
            hint=f"可选：{', '.join(available_providers())}；或设 ATELIER_MOCK=1 跑 mock",
        )
    module_path, _, cls_name = target.partition(":")
    try:
        module = __import__(module_path, fromlist=[cls_name])
        cls = getattr(module, cls_name)
    except Exception as exc:
        raise HarnessError(
            f"harness provider「{wanted}」装载失败：{type(exc).__name__}: {exc}",
            detail={"target": target, "error": str(exc)},
            hint="跑 `atelier doctor` 看环境诊断；或用 ATELIER_MOCK=1 先跑通流程",
        ) from exc
    return cls(**kwargs)  # type: ignore[no-any-return]


def get_harness() -> Harness:
    """进程内单例。业务层统一从这里取。"""
    global _instance
    if _instance is None:
        _instance = create_harness()
    return _instance


def set_harness(harness: Harness | None) -> None:
    """替换单例（测试与热切换用）。传 None 等于 :func:`reset_harness`。"""
    global _instance
    _instance = harness


def current_harness() -> Harness | None:
    """已创建的单例（没有则 None）。启动/关闭流程用它，避免被动实例化 provider。"""
    return _instance


def reset_harness() -> None:
    """丢掉单例，下次 :func:`get_harness` 重新按配置创建。"""
    global _instance
    _instance = None
