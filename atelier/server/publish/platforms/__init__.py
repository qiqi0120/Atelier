"""SPEC-06 §5 · 平台 adapter 注册表。

**新增平台规则**：只允许新增一个 ``platforms/<name>.py`` 并在这里加**一行**映射，
不改 :mod:`atelier.server.publish.platforms.base`。
"""

from __future__ import annotations

from ...errors import ValidationError
from .base import AuthState, BaseAdapter, PublishAdapter, PublishResult
from .douyin import adapter as douyin_adapter
from .wechat_mp import adapter as wechat_mp_adapter
from .xiaohongshu import adapter as xhs_adapter

__all__ = [
    "ADAPTERS",
    "AuthState",
    "BaseAdapter",
    "DouyinAdapter",
    "PublishAdapter",
    "PublishResult",
    "WechatMPAdapter",
    "XHSAdapter",
    "get_adapter",
    "known_platforms",
]

#: 平台 key → adapter 单例。
#:
#: **直接复用各模块里的单例**（而不是 ``DouyinAdapter()`` 新建一个）：
#: 否则同一平台会存在两个实例，测试与后续 M4 真实实现替换单例时会对不上——
#: ``get_adapter()`` 拿到的那个对象根本不是被替换的那个。
ADAPTERS: dict[str, BaseAdapter] = {
    "xhs": xhs_adapter,
    "dy": douyin_adapter,
    "gzh": wechat_mp_adapter,
}


def known_platforms() -> list[str]:
    return list(ADAPTERS)


def get_adapter(platform: str) -> BaseAdapter:
    """按 key 取 adapter；未知平台抛 ``ValidationError``（不留裸 KeyError）。"""
    ad = ADAPTERS.get((platform or "").strip().lower())
    if ad is None:
        raise ValidationError(
            f"不支持的平台：{platform}",
            detail={"platform": platform, "supported": known_platforms()},
            hint=f"可选平台：{', '.join(known_platforms())}",
        )
    return ad
