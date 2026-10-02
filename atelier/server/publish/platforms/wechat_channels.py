"""SPEC-14 · 微信视频号 adapter（M4 平台扩展）。

平台特性（PRD §10.4）：**仅视频**，标题（描述位）按公开资料设定 ≤ 16 字，
正文位 ≤ 1000 字。必须挂视频。
"""

from __future__ import annotations

from ...core.models import PlatformVariant
from .base import BaseAdapter, PublishResult, has_asset_kind

__all__ = ["WechatChannelsAdapter", "adapter"]


class WechatChannelsAdapter(BaseAdapter):
    platform = "wcs"
    display_name = "视频号"
    forms = ("video",)
    needs_cover = False
    cover_ratio = None
    body_max = 1000
    title_max = 16
    sms_wall = False

    def _extra_check(self, v: PlatformVariant, assets: list[str]) -> PublishResult | None:
        if not has_asset_kind(assets, "video"):
            return PublishResult(
                ok=False,
                error_code="wcs_form_rejected",
                error="视频号只接受视频，当前素材形态不合法",
                raw={"assets": assets, "forms": list(self.forms)},
            )
        return None


#: 模块级单例（``platforms.get_adapter`` 返回它）
adapter = WechatChannelsAdapter()
