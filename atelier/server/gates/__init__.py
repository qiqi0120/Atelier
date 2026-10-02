"""SPEC-01 §5 · 内置门禁（M1 交付 4 个）。

新门禁只能新增 ``gates/<name>.py`` 并在里面 ``@register``，不得改本文件
（SPEC-00 §3「新能力走注册表」硬规则）。
"""

from __future__ import annotations

from .base import GateInput, GateItem, GateReport, Severity

__all__ = ["GateInput", "GateItem", "GateReport", "Severity"]
