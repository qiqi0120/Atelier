"""SPEC-02 · 账号画像域。

四个模块，职责单一：

- :mod:`store`   —— 画像/记忆 CRUD + ``profiles/<id>.md`` 双写（SQLite 为准，md 更新则反向导入）
- :mod:`prompt`  —— ★ 画像 → 消息前缀（每轮现拼，不落全局文件、不写库字段）
- :mod:`wizard`  —— 新建向导 4 步状态机（可中途跳过、可中途退出恢复）
- ``atelier/server/api/profile.py`` —— 13 个端点

**本域的立身之本是 :mod:`prompt`**：所有 AI 产出都经过它，而它必须做到两个画像
并发时互不影响（PRD 4.2 验收 4、5）。因此这里没有任何「当前画像」全局状态，
前缀永远由传入的 ``Profile`` 现场拼装。
"""

from __future__ import annotations

from . import prompt, store, wizard

__all__ = ["prompt", "store", "wizard"]
