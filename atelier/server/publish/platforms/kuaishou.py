"""SPEC-14 · 快手 adapter（M4 平台扩展）。

平台特性（PRD §10.4）：图文 / 视频都发，扫码登录；正文上限按公开资料设定 1000 字，
标题 20 字。不强制封面（上传时可自动取首帧/首图）。
"""

from __future__ import annotations

from .base import BaseAdapter

__all__ = ["KuaishouAdapter", "adapter"]


class KuaishouAdapter(BaseAdapter):
    platform = "ks"
    display_name = "快手"
    forms = ("image", "video")
    needs_cover = False
    cover_ratio = None
    body_max = 1000
    title_max = 20
    sms_wall = False


#: 模块级单例（``platforms.get_adapter`` 返回它）
adapter = KuaishouAdapter()
