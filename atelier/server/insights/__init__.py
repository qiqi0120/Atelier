"""Atelier 分析域（M2-3a，SPEC-11）。

四个即席 AI 工具：:mod:`competitor`（F-D10 竞品分析）· :mod:`strategy`（F-E12
内容策略）· :mod:`audience`（F-E14 受众画像）· :mod:`diagnose`（F-E13 账号诊断，
诚实模式）。AI 调用与门禁**复用** topics 域原语（SPEC-11 §0 D1），全部不落库。
订阅 / RSS（F-D5/D7）属 M2-3b，走 ``discovery`` 包（尚未创建）。
"""

from . import audience, competitor, diagnose, service, strategy

__all__ = ["audience", "competitor", "diagnose", "service", "strategy"]
