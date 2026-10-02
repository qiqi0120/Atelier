"""SPEC-05 · 内容库域（项目化归档 / 目录树 / Range 流式 / 删除保护）。

分层约定（与仓库其它域一致）：

- :mod:`atelier.server.library.service` 纯服务层，**只拼路径**（全部走
  :mod:`atelier.server.paths`），抛 :class:`~atelier.server.errors.AtelierError` 子类。
- :mod:`atelier.server.api.library` 只做 HTTP 形状转换，不含业务判断。
"""

from __future__ import annotations

from . import service

__all__ = ["service"]
