"""SPEC-06 · 发布中心域。

本域的模块与职责：

===========================  ===============================================
:mod:`wordcount`             平台字数计数（中文口径，**前端只消费结果**）
:mod:`adapt`                 平台约束表 + 多平台适配流式生成（F-G10）
:mod:`precheck`              发布前预检，硬门禁 / 软提醒分级（F-G12 / F-G13）
:mod:`dispatcher`            发布编排 + 状态机 + 错误码人话映射（SPEC-06 §4）
:mod:`platforms`             三个平台 adapter（SPEC-06 §5），新增平台只加一个文件
``api/publish.py``           14 个端点 + 草稿/发布记录的 SQLite 读写
===========================  ===============================================

**已知缺口（SPEC-06 §0 已声明）**：真实发布依赖真实登录态 + 平台风控，本批
``dry_run=True``。adapter 的**校验全部真实执行**，只有最后「发出」是模拟，
且响应里带 ``dry_run: true`` 与人话 notice，前端必须原样展示，不许让用户
误以为真发出去了。真实发布属 M4。
"""

from __future__ import annotations

from . import adapt, dispatcher, platforms, precheck, wordcount
from .adapt import PLATFORM_LIMITS, adapt_platforms, build_adapt_prompt, stream_adapt
from .dispatcher import ERROR_HINTS, DispatchResult, PlatformRun, error_hint, publish_draft
from .platforms import ADAPTERS, get_adapter
from .precheck import precheck_blocked, run_precheck
from .wordcount import count_platform_chars, crop_to_limit

__all__ = [
    "ADAPTERS",
    "ERROR_HINTS",
    "PLATFORM_LIMITS",
    "DispatchResult",
    "PlatformRun",
    "adapt",
    "adapt_platforms",
    "build_adapt_prompt",
    "count_platform_chars",
    "crop_to_limit",
    "dispatcher",
    "error_hint",
    "get_adapter",
    "platforms",
    "precheck",
    "precheck_blocked",
    "publish_draft",
    "run_precheck",
    "stream_adapt",
    "wordcount",
]
