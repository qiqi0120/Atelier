"""SPEC-06 §5 · 抖音 adapter。

平台特性：**仅视频**（图文发不了），标题 = 口播标题 ≤ 55 字，正文 ≤ 55 字，
不需要封面图（视频首帧即是封面），发布时可能弹**短信墙**（5 分钟内有效）。
"""

from __future__ import annotations

from ...core.models import PlatformVariant
from .base import BaseAdapter, PublishResult, has_asset_kind

__all__ = ["DouyinAdapter", "adapter"]


class DouyinAdapter(BaseAdapter):
    platform = "dy"
    display_name = "抖音"
    forms = ("video",)
    needs_cover = False
    cover_ratio = None
    body_max = 55
    title_max = 55
    sms_wall = True

    def _extra_check(self, v: PlatformVariant, assets: list[str]) -> PublishResult | None:
        """抖音只吃视频。挂了图片 = 形态不合法，必须在发之前拦住。"""
        if not has_asset_kind(assets, "video"):
            has_image = has_asset_kind(assets, "image")
            return PublishResult(
                ok=False,
                error_code="dy_form_rejected",
                error=(
                    "抖音仅支持视频，"
                    + ("当前只挂了图片，形态不合法" if has_image else "没有可发布的视频素材")
                ),
                raw={"assets": assets, "required_forms": ["video"]},
            )
        return None


#: 模块级单例
adapter = DouyinAdapter()
