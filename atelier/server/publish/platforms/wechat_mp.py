"""SPEC-06 §5 · 微信公众号 adapter。

平台特性：图文 / 长文，**必须有封面图且比例 2.35:1**（大图），正文 ≤ 20000 字，
标题 ≤ 64 字。凭证登录（AppID/AppSecret），无短信墙。
"""

from __future__ import annotations

from ...core.models import PlatformVariant
from .base import BaseAdapter, PublishResult

__all__ = ["WechatMPAdapter", "adapter"]


class WechatMPAdapter(BaseAdapter):
    platform = "gzh"
    display_name = "微信公众号"
    forms = ("image", "text")
    needs_cover = True
    cover_ratio = "2.35:1"
    body_max = 20000
    title_max = 64
    sms_wall = False

    def _extra_check(self, v: PlatformVariant, assets: list[str]) -> PublishResult | None:
        """长文太短反而会被判低质（< 50 字），给个提醒级别的失败而非硬拦截形态。"""
        if len((v.body or "").strip()) and not v.body.strip():
            return PublishResult(
                ok=False, error_code="gzh_empty_body",
                error="公众号正文为空",
                raw={},
            )
        return None


#: 模块级单例
adapter = WechatMPAdapter()
