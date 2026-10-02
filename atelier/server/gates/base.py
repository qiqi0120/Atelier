"""SPEC-01 §5 · 门禁框架（契约层）。

**不 import 任何具体实现，也不 import 业务模型**（:class:`GateInput` 里的
``profile`` 是前向引用字符串，运行期不解析），避免 ``core.models`` ↔ ``gates`` 循环依赖。

PRD 原则二：AI 产出必须过确定性门禁；门禁分两级（SPEC-01 §5）：

- ``BLOCK`` 硬门禁：必须修，命中即阻断落盘
- ``WARN``  软提醒：只告警（AI 味重、人设不符）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "Gate",
    "GateInput",
    "GateItem",
    "GateReport",
    "Severity",
    "ai_item",
]


class Severity(str, Enum):
    """门禁分级。值即 API 传输值（``"block"`` / ``"warn"``），前端按它上色。"""

    BLOCK = "block"  # 阻断：必须修
    WARN = "warn"  # 软提醒：只告警（PRD 原则二）


@dataclass
class GateInput:
    """门禁输入。字段名与 SPEC-01 §5 冻结一致。"""

    text: str
    platform: str | None  # 按平台判字数
    title: str | None
    image_paths: list[str]  # 视觉质检用（M3 扩展）
    profile: Profile | None = None  # noqa: F821 - 人设一致性用；前向引用避免循环依赖

    @classmethod
    def of(
        cls,
        text: str = "",
        *,
        platform: str | None = None,
        title: str | None = None,
        image_paths: list[str] | None = None,
        profile: Any = None,
    ) -> GateInput:
        """便利构造：agent / API 侧只关心几个关键字时用。"""
        return cls(
            text=text or "",
            platform=platform,
            title=title,
            image_paths=list(image_paths or []),
            profile=profile,
        )


@dataclass
class GateItem:
    """单条门禁结果。字段名在 SPEC-01 §11 冻结。"""

    gate: str  # 门禁 id
    label: str  # "小红书正文字数"
    severity: Severity
    passed: bool
    actual: int | str | None
    limit: int | str | None
    message: str  # 人话
    fix_hint: str | None  # 怎么改

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "label": self.label,
            "severity": self.severity.value if isinstance(self.severity, Severity) else str(self.severity),
            "passed": bool(self.passed),
            "actual": self.actual,
            "limit": self.limit,
            "message": self.message,
            "fix_hint": self.fix_hint,
        }


@dataclass
class GateReport:
    """一次门禁跑批的汇总。"""

    items: list[GateItem] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(i.severity == Severity.BLOCK and not i.passed for i in self.items)

    @property
    def failed(self) -> list[GateItem]:
        return [i for i in self.items if not i.passed]

    @property
    def warnings(self) -> list[GateItem]:
        """只告警、不阻断的失败项（AI 味重这类）。"""
        return [i for i in self.items if not i.passed and i.severity == Severity.WARN]

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "items": [i.to_dict() for i in self.items],
            "summary": {
                "total": len(self.items),
                "failed": len(self.failed),
                "blocked_items": sum(1 for i in self.items if not i.passed and i.severity == Severity.BLOCK),
                "warn_items": len(self.warnings),
            },
        }

    def fix_hints(self) -> list[str]:
        return [i.fix_hint for i in self.failed if i.fix_hint]


@runtime_checkable
class Gate(Protocol):
    """门禁插件。实现类只要有 ``id`` / ``label`` / ``run`` 就能注册。"""

    id: str
    label: str
    severity: Severity

    def run(self, content: GateInput) -> GateItem: ...


def ai_item(
    *,
    gate: str,
    label: str,
    passed: bool,
    actual: int | str | None,
    limit: int | str | None,
    message: str,
    fix_hint: str | None,
    severity: Severity = Severity.BLOCK,
) -> GateItem:
    """门禁实现里构造 :class:`GateItem` 的快捷函数。"""
    return GateItem(
        gate=gate,
        label=label,
        severity=severity,
        passed=passed,
        actual=actual,
        limit=limit,
        message=message,
        fix_hint=fix_hint,
    )
