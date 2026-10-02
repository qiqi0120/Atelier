"""SPEC-06 §5 · ``PublishAdapter`` 抽象。

**新增平台规则（SPEC-06 §5）**：只允许新增一个 ``platforms/<name>.py``，
不改本文件。所以这里给的是**协议 + 可复用的校验基类**，平台差异全部留在子类。

三件事在这里收口，各平台不重复：

1. :class:`AuthState` / :class:`PublishResult` —— 两个返回类型
2. :class:`BaseAdapter` —— 共用的**真实校验**：字数、封面、形态、登录态
3. ``dry_run`` —— 最后一步才走模拟，**响应里必须标明是模拟执行**
   （SPEC-06 §0 已声明这是本批的已知缺口，真实发布属 M4）
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ...core.models import PlatformVariant

log = logging.getLogger("atelier.publish.platform")

__all__ = [
    "AuthState",
    "BaseAdapter",
    "PublishAdapter",
    "PublishResult",
    "cover_ok",
    "has_asset_kind",
]


@dataclass
class AuthState:
    """登录态。**真校验**，不只看标记文件（PRD F-G24）。"""

    platform: str
    logged_in: bool
    account: str | None = None
    need_sms: bool = False
    message: str = ""
    verified_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "logged_in": self.logged_in,
            "account": self.account,
            "need_sms": self.need_sms,
            "message": self.message,
            "verified_at": self.verified_at,
        }


@dataclass
class PublishResult:
    """SPEC-06 §5 冻结形状。"""

    ok: bool
    url: str | None = None
    error_code: str | None = None
    error: str | None = None
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "url": self.url,
            "error_code": self.error_code,
            "error": self.error,
            "raw": self.raw,
        }


@runtime_checkable
class PublishAdapter(Protocol):
    """平台 adapter 协议（SPEC-06 §5）。"""

    platform: str

    async def check_auth(self) -> AuthState: ...

    async def publish(self, v: PlatformVariant, assets: list[str], dry_run: bool) -> PublishResult: ...

    async def schedule(self, v: PlatformVariant, at: datetime) -> None: ...


# ---------------------------------------------------------------------------
# 资产判定
# ---------------------------------------------------------------------------

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".gif"}
_VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


def _ext(path: str) -> str:
    p = str(path or "").lower()
    dot = p.rfind(".")
    slash = max(p.rfind("/"), p.rfind("\\"))
    return p[dot:] if dot > slash and dot > 0 else ""


def has_asset_kind(assets: list[str], kind: str) -> bool:
    """附件里有没有某一类素材（image / video）。"""
    exts = _IMAGE_EXT if kind == "image" else _VIDEO_EXT if kind == "video" else set()
    return any(_ext(a) in exts for a in assets or [])


def cover_ok(assets: list[str], ratio: str | None) -> tuple[bool, str]:
    """封面图比例是否合规。

    **只能按文件名判定比例**——真实尺寸要读图片二进制，属内容库域（M3 视觉质检）。
    这里做的是：有没有封面图，以及文件名里声明的尺寸是否匹配目标比例。
    拿不到尺寸时**放行**（比例未知 ≠ 违规），但文案里要说明「未标注尺寸，未校验比例」。
    """
    covers = [a for a in assets or [] if _ext(a) in _IMAGE_EXT]
    if not covers:
        return False, "没有封面图"
    if not ratio:
        return True, covers[0]
    want = _ratio_nums(ratio)
    for c in covers:
        nums = _size_in_name(c)
        if nums is None:
            continue
        w, h = nums
        if h == 0:
            continue
        got = w / h
        if abs(got - want) <= 0.12:  # ±0.12 容差：3:4 = 0.75，2.35:1 = 2.35
            return True, c
    if all(_size_in_name(c) is None for c in covers):
        return True, f"{covers[0]}（未标注尺寸，未校验比例 {ratio}）"
    return False, f"{covers[0]} 比例不符合 {ratio}"


def _ratio_nums(ratio: str) -> float:
    a, _, b = str(ratio).partition(":")
    try:
        return float(a) / float(b)
    except (ValueError, ZeroDivisionError):
        return 1.0


def _size_in_name(name: str) -> tuple[int, int] | None:
    """从 ``card-01-1080x1440.png`` / ``cover 1080×1440.png`` 里抠出宽高。"""
    import re

    m = re.search(r"(\d{2,5})\s*[x×*]\s*(\d{2,5})", str(name), re.IGNORECASE)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


# ---------------------------------------------------------------------------
# 共用基类
# ---------------------------------------------------------------------------


class BaseAdapter:
    """平台 adapter 基类：真校验 + dry-run 打日志。

    子类必须给：``platform`` / ``display_name`` / ``forms`` / ``needs_cover`` /
    ``cover_ratio`` / ``body_max`` / ``title_max``，以及平台特有的
    :meth:`_extra_check`（形态校验等）。
    """

    platform: str = ""
    display_name: str = ""
    forms: tuple[str, ...] = ()
    needs_cover: bool = False
    cover_ratio: str | None = None
    body_max: int = 0
    title_max: int = 0
    #: 该平台「登录态正常但发布时可能弹短信墙」
    sms_wall: bool = False

    # -- 登录态 ------------------------------------------------------------

    async def check_auth(self) -> AuthState:
        """真校验登录态。

        本批不接扫码（M4），所以真校验 = 查 ``platform_creds`` 表里该平台的
        ``state``，而不是看「有没有标记文件」。查不到记录 = 未登录 = 阻断。
        """
        from ...core.db import get_conn

        try:
            row = get_conn().execute(
                "SELECT account, state, verified_at FROM platform_creds WHERE platform=? ORDER BY created_at DESC LIMIT 1",
                (self.platform,),
            ).fetchone()
        except Exception as exc:  # noqa: BLE001 - 查不到就按未登录，绝不放行
            log.warning("check_auth query failed: %s (%s)", self.platform, exc)
            return AuthState(
                platform=self.platform, logged_in=False,
                message=f"{self.display_name}登录态查询失败，按未登录处理",
            )

        if row is None:
            return AuthState(
                platform=self.platform, logged_in=False,
                message=f"{self.display_name}未登录，去「账号登录」扫码后再发",
            )
        state = str(row["state"] or "unknown")
        account = row["account"]
        if state == "valid":
            return AuthState(
                platform=self.platform, logged_in=True, account=account,
                need_sms=self.sms_wall,
                message=f"{self.display_name}登录态有效（{account or '未记账号'}）",
                verified_at=row["verified_at"],
            )
        if state == "expired":
            return AuthState(
                platform=self.platform, logged_in=False, account=account,
                message=f"{self.display_name}登录态已过期，需重新扫码",
                verified_at=row["verified_at"],
            )
        return AuthState(
            platform=self.platform, logged_in=False, account=account,
            message=f"{self.display_name}登录态未校验过（state={state}），发前请先登录",
            verified_at=row["verified_at"],
        )

    # -- 校验 --------------------------------------------------------------

    def validate(self, v: PlatformVariant, assets: list[str]) -> PublishResult | None:
        """返回 ``None`` 表示校验通过；否则是失败结果（含错误码）。"""
        from ..wordcount import count_platform_chars

        limit = self.body_max
        actual = count_platform_chars(v.body, self.platform)
        if actual > limit:
            return PublishResult(
                ok=False, error_code="over_limit",
                error=f"{self.display_name}正文 {actual}/{limit} 字，超限 {actual - limit} 字",
                raw={"actual": actual, "limit": limit},
            )
        t_limit = self.title_max
        t_actual = count_platform_chars(v.title, self.platform)
        if t_actual > t_limit:
            return PublishResult(
                ok=False, error_code="over_limit",
                error=f"{self.display_name}标题 {t_actual}/{t_limit} 字，超限 {t_actual - t_limit} 字",
                raw={"actual": t_actual, "limit": t_limit},
            )
        if self.needs_cover:
            ok, detail = cover_ok(assets, self.cover_ratio)
            if not ok:
                return PublishResult(
                    ok=False, error_code="gzh_no_cover" if self.platform == "gzh" else "xhs_no_cover",
                    error=f"{self.display_name}{detail}",
                    raw={"cover_ratio": self.cover_ratio, "assets": assets},
                )
        return self._extra_check(v, assets)

    def _extra_check(self, v: PlatformVariant, assets: list[str]) -> PublishResult | None:
        """平台特有校验（形态等）。默认无额外要求。"""
        return None

    # -- 发布 --------------------------------------------------------------

    async def publish(self, v: PlatformVariant, assets: list[str], dry_run: bool = True) -> PublishResult:
        """校验通过后走**模拟发布**。

        ★ ``dry_run=True`` 是本批的默认且唯一可跑的路径（SPEC-06 §0 已声明的缺口）：
        真实发布需要真实账号与平台风控验证，属 M4。这里**绝不假装成功**——
        ``raw`` 里明确带 ``dry_run: true`` 与说明，调用方必须把它透传给前端。
        """
        bad = self.validate(v, assets)
        if bad is not None:
            return bad
        if not dry_run:
            # 真实发布入口留在这里：M4 接入真实账号与风控验证后替换本分支
            log.warning("real publish requested but not implemented yet: %s", self.platform)
            return PublishResult(
                ok=False, error_code="not_implemented",
                error="真实发布尚未接入（M4）：需要真实账号登录态与平台风控验证",
                raw={"dry_run": False, "implemented": False},
            )
        ref = f"dryrun-{self.platform}-{uuid.uuid4().hex[:8]}"
        log.info(
            "DRY-RUN publish (simulated, nothing was actually sent): platform=%s ref=%s title=%r chars=%d",
            self.platform, ref, v.title[:30], v.char_count,
        )
        return PublishResult(
            ok=True, url=None, error_code=None, error=None,
            raw={
                "dry_run": True,
                "simulated": True,
                "ref": ref,
                "notice": "模拟执行（dry-run）：未向平台真实发出，草稿与记录已保存",
                "platform": self.platform,
            },
        )

    async def schedule(self, v: PlatformVariant, at: datetime) -> None:
        """排期发布（P2）。

        本批只落意图，不真排队：真实定时投递需要常驻进程与平台侧定时接口（M4）。
        """
        log.info("schedule intent recorded (not queued): platform=%s at=%s", self.platform, at.isoformat())
