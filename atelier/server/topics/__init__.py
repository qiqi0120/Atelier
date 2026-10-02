"""Atelier 选题域（M2-1，SPEC-08）。

模块切分：:mod:`service`（池 CRUD + 共用 AI/门禁路径）· :mod:`decode`（爆款拆解）·
:mod:`score`（7 维评分）· :mod:`matrix`（内容矩阵）· :mod:`hooks`（标题 Hook）。
"""

from . import decode, hooks, matrix, score, service

__all__ = ["decode", "hooks", "matrix", "score", "service"]
