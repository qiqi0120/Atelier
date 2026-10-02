"""SPEC-14 · B站 adapter（M4 平台扩展）。

平台特性（PRD §10.4）：**仅视频**（走 biliup 工具链的方向，本批 dry-run），
标题 ≤ 80 字，简介（正文位）≤ 2000 字，必须挂视频。
"""

from __future__ import annotations

from ...core.models import PlatformVariant
from .base import BaseAdapter, PublishResult, has_asset_kind

__all__ = ["BilibiliAdapter", "adapter"]


class BilibiliAdapter(BaseAdapter):
    platform = "bilibili"
    display_name = "B站"
    forms = ("video",)
    needs_cover = False
    cover_ratio = None
    body_max = 2000
    title_max = 80
    sms_wall = False

    def _extra_check(self, v: PlatformVariant, assets: list[str]) -> PublishResult | None:
        if not has_asset_kind(assets, "video"):
            return PublishResult(
                ok=False,
                error_code="bilibili_form_rejected",
                error="B站只接受视频，当前素材形态不合法",
                raw={"assets": assets, "forms": list(self.forms)},
            )
        return None


#: 模块级单例（``platforms.get_adapter`` 返回它）
adapter = BilibiliAdapter()
