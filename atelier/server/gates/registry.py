"""SPEC-01 §5 · 门禁插件注册表。

**新门禁只允许新增 ``gates/<name>.py`` 并在其中 ``@register``**（SPEC-00 §3 硬规则），
不得修改本文件来加能力。

``ensure_builtins()`` 用 ``importlib`` 惰性导入 4 个内置门禁，理由是：内置门禁模块
反过来 ``from .registry import register``，顶部直接 import 会形成循环依赖。惰性导入
还顺带解决了「先 import 某个内置门禁」时的半初始化顺序问题——注册发生在装饰器执行时，
谁先被 import 谁先注册，registry 拿到的始终是最终状态。
"""

from __future__ import annotations

import importlib
from typing import Any

from .base import Gate, GateInput, GateReport

__all__ = [
    "BUILTIN_MODULES",
    "clear",
    "get_gate",
    "list_gates",
    "register",
    "registry_errors",
    "run_gates",
]

_registry: dict[str, Gate] = {}
_errors: dict[str, str] = {}
_loaded = False
#: 已经被 reload 过的内置模块（避免每次 ensure 都 reload）
_reloaded: set[str] = set()

#: SPEC-01 §5 的 4 个内置门禁（M1 交付）
BUILTIN_MODULES: tuple[str, ...] = (
    "ai_flavor",
    "compliance",
    "secret_scan",
    "wordcount",
)


def register(gate: Gate | type[Gate]) -> Any:
    """注册一个门禁；既可直接调用，也支持 SPEC-01 §5 的装饰器写法 ``@register``。

    传入**类**时会自动实例化再登记——这样 ``@register`` 装饰在类上最自然，
    而注册表里存的始终是**实例**，``run_gates`` 才能 ``gate.run(content)``。
    返回登记后的对象（实例）。
    """
    obj: Any = gate() if isinstance(gate, type) else gate
    gid = getattr(obj, "id", None)
    if not gid or not isinstance(gid, str):
        raise ValueError(f"门禁缺少合法的 id: {gate!r}")
    if not callable(getattr(obj, "run", None)):
        raise TypeError(f"门禁 {gid} 没有 run(content) 方法")
    _registry[gid] = obj
    return obj


def clear() -> None:
    """清空注册表。下次 :func:`ensure_builtins` 会 reload 内置门禁并重新登记。"""
    _registry.clear()
    _errors.clear()
    global _loaded
    _loaded = False


def ensure_builtins() -> None:
    """幂等装载 4 个内置门禁，触发它们的登记。

    用 ``importlib.reload`` 而不是普通 import：普通 import 在模块已被缓存时会
    直接返回半初始化/旧对象，``@register`` 不会重跑，``clear()`` 之后就再也
    装不回来了。reload 会重跑模块级装饰器，所以 clear → ensure 一定装得回来。
    """
    global _loaded
    if _loaded:
        return
    for name in BUILTIN_MODULES:
        mod_name = f"{__package__}.{name}"
        try:
            mod = importlib.import_module(mod_name)
            if mod_name in _reloaded:
                importlib.reload(mod)
        except Exception as exc:  # noqa: BLE001 - 诊断要留痕，不能静默
            _errors[name] = f"{type(exc).__name__}: {exc}"
    _reloaded.update(f"{__package__}.{name}" for name in BUILTIN_MODULES)
    _loaded = True


def get_gate(gate_id: str) -> Gate | None:
    ensure_builtins()
    return _registry.get(gate_id)


def list_gates() -> list[dict[str, Any]]:
    """给前端「门禁说明」用。"""
    ensure_builtins()
    out: list[dict[str, Any]] = []
    for gid, gate in sorted(_registry.items()):
        sev = getattr(gate, "severity", None)
        out.append(
            {
                "id": gid,
                "label": getattr(gate, "label", gid),
                "severity": sev.value if hasattr(sev, "value") else str(sev),
                "doc": (getattr(gate, "doc", "") or (gate.__doc__ or "").strip().split("\n")[0]),
            }
        )
    return out


def registry_errors() -> dict[str, str]:
    """内置门禁装载失败的原因（doctor 诊断用，PRD 原则四）。"""
    ensure_builtins()
    return dict(_errors)


def run_gates(content: GateInput, gate_ids: list[str] | None = None) -> GateReport:
    """跑门禁。``gate_ids`` 为 None 时跑全部。

    单个门禁自身抛异常**不吞**：记成一条 BLOCK 失败项（fail-closed 的最后一道兜底），
    这样「门禁挂了」不会被误读成「门禁通过」。
    """
    ensure_builtins()
    if gate_ids is None:
        targets = [_registry[k] for k in sorted(_registry)]
    else:
        targets = []
        for gid in gate_ids:
            gate = _registry.get(gid)
            if gate is None:
                targets.append(_MissingGate(gid))
            else:
                targets.append(gate)

    items = []
    for gate in targets:
        try:
            item = gate.run(content)
        except Exception as exc:  # noqa: BLE001
            item = _error_item(gate, exc)
        items.append(item)
    return GateReport(items=items)


def _error_item(gate: Any, exc: Exception) -> Any:
    from .base import GateItem, Severity  # 局部 import：避免模块级循环

    gid = getattr(gate, "id", type(gate).__name__)
    return GateItem(
        gate=gid,
        label=f"{getattr(gate, 'label', gid)}（门禁自身异常）",
        severity=Severity.BLOCK,
        passed=False,
        actual=f"{type(exc).__name__}",
        limit=None,
        message=f"门禁 {gid} 执行失败，按未通过处理：{exc}",
        fix_hint="跑 `atelier doctor` 看诊断；内容未落盘，改完重试",
    )


class _MissingGate:
    """请求了不存在的门禁 id 时的占位实现（也要显式报错，不能当通过）。"""

    id = "_missing"
    label = "未知门禁"
    severity = "block"

    def __init__(self, wanted: str) -> None:
        self.id = wanted
        self._wanted = wanted

    def run(self, content: GateInput) -> Any:
        from .base import GateItem, Severity

        known = ", ".join(sorted(_registry)) or "（无）"
        return GateItem(
            gate=self.id,
            label="未知门禁",
            severity=Severity.BLOCK,
            passed=False,
            actual=self._wanted,
            limit=known,
            message=f"没有这个门禁：{self._wanted}",
            fix_hint=f"可用门禁：{known}",
        )
