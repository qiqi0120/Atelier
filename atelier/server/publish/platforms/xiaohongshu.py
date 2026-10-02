"""SPEC-06 §5 · 小红书 adapter。

平台特性：图文 / 视频都发，**必须有封面图且比例 3:4**，正文 ≤ 1000 字，标题 ≤ 20 字。
"""

from __future__ import annotations

from ...core.models import PlatformVariant
from .base import BaseAdapter, PublishResult, has_asset_kind

__all__ = ["XHSAdapter", "adapter"]


class XHSAdapter(BaseAdapter):
    platform = "xhs"
    display_name = "小红书"
    forms = ("image", "video")
    needs_cover = True
    cover_ratio = "3:4"
    body_max = 1000
    title_max = 20
    sms_wall = False

    def _extra_check(self, v: PlatformVariant, assets: list[str]) -> PublishResult | None:
        """小红书至少要有一张图或一条视频，否则连草稿都存不进去。"""
        if not (has_asset_kind(assets, "image") or has_asset_kind(assets, "video")):
            return PublishResult(
                ok=False, error_code="xhs_no_media",
                error="小红书图文至少要挂 1 张图或 1 条视频",
                raw={"assets": assets},
            )
        return None


#: 模块级单例（``platforms.get_adapter`` 返回它）
adapter = XHSAdapter()
