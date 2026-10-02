"""Atelier 后端服务包。

**依赖方向（禁止反向 import，会造成循环依赖）**::

    paths  → errors
    core   → gates.base, paths, errors
    gates  → errors, gates.base（不依赖 core）
    harness→ errors, paths, gates, core（不依赖 api）
    api    → core, harness, gates, paths, errors
    main   → 上面全部

:harness:`harness/base.py` 与 :mod:`atelier.server.gates.base` 是纯契约层，
不得 import 任何具体实现（含 ``claude_agent_sdk``）。
"""

from __future__ import annotations

__all__: list[str] = []
