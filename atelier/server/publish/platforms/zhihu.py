"""SPEC-14 · 知乎 adapter（M4 平台扩展）。

平台特性（PRD §10.4）：回答 + 评论为主（本批支持 text 形态的回答发布），
正文上限按公开资料设定 20000 字，标题 100 字。不强制封面。
"""

from __future__ import annotations

from ...core.models import PlatformVariant
from .base import BaseAdapter, PublishResult

__all__ = ["ZhihuAdapter", "adapter"]


class ZhihuAdapter(BaseAdapter):
    platform = "zhihu"
    display_name = "知乎"
    forms = ("text",)
    needs_cover = False
    cover_ratio = None
    body_max = 20000
    title_max = 100
    sms_wall = False

    def _extra_check(self, v: PlatformVariant, assets: list[str]) -> PublishResult | None:
        """知乎是观点平台：正文过短（<50 字）撑不起一个回答，按平台特性提示。"""
        from ..wordcount import count_platform_chars

        if count_platform_chars(v.body, self.platform) < 50:
            return PublishResult(
                ok=False,
                error_code="zhihu_too_short",
                error="知乎回答至少 50 字（观点平台，太短没信息量）",
                raw={"min": 50},
            )
        return None


#: 模块级单例（``platforms.get_adapter`` 返回它）
adapter = ZhihuAdapter()
