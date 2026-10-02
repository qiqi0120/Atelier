"""Atelier 日历域（M2-2 前半，SPEC-09）。

模块切分：:mod:`service`（事件 CRUD + 提醒窗口 + 内置节点补种）·
:mod:`suggest`（F-E7 日历建议；AI 调用与门禁**复用** topics 域的原语，
SPEC-09 §0 D1，不另写一条调用路径）。
"""

from . import service, suggest

__all__ = ["service", "suggest"]
