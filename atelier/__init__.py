"""Atelier · 面向社交媒体创作者的私有内容工作台。

本包分层（SPEC-00 §2）：

- ``atelier.server``  FastAPI 后端（paths / errors / core / harness / gates / api）
- ``atelier.cli``      命令行入口（web / chat / skill / doctor / ping）
- ``atelier.skills``   技能资产（SKILL.md），由 W1-B 维护

版本号单点来源：``atelier.__version__``。
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
