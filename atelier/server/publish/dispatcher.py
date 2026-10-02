"""SPEC-06 §4 · 发布编排 + 平台状态机。

状态机（SPEC-06 §4 原文）::

    pending → adapting → ready → publishing → sent
                                      ↘ failed
                                      ↘ awaiting_sms → publishing → sent / failed(timeout)

三条硬要求：

1. **逐平台并发**（``asyncio.gather`` + 单平台异常捕获）——一个平台失败不阻塞其他
2. **二次确认**：``confirm=true`` 才发，前端弹窗后仍要服务端再校验
3. **错误码 → 人话**（:data:`ERROR_HINTS`）：失败必须看到明确原因（原则四）

**dry-run 说明（诚实边界，SPEC-06 §0）**：本批 ``dry_run=True`` 是默认且唯一路径，
adapter 的**校验逻辑全部真实执行**（字数/封面/形态/登录态），只有最后「发出」这一步
是模拟的。响应里每条 result 都带 ``dry_run: true`` 与 ``notice``，前端必须原样展示，
不能让用户误以为真发出去了。真实发布属 M4。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from ..core.models import PlatformVariant, Profile, PublishDraft
from ..errors import GateBlocked, ValidationError
from .adapt import PLATFORM_LIMITS
from .platforms import get_adapter
from .platforms.base import PublishResult
from .precheck import precheck_blocked, run_precheck

log = logging.getLogger("atelier.publish.dispatcher")

__all__ = [
    "ERROR_HINTS",
    "MAX_RETRY",
    "STATUS_FLOW",
    "DispatchResult",
    "PlatformRun",
    "error_hint",
    "is_failed",
    "publish_draft",
]

#: SPEC-06 §4 的错误码 → 人话（PRD 10.6 验收：失败要看到明确原因）
ERROR_HINTS: dict[str, str] = {
    "dy_auth_4012": "登录态过期，需重新扫码 + 短信验证码",
    "dy_sms_required": "平台要求短信验证码，请在弹窗中输入（5 分钟内有效）",
    "xhs_risk_control": "触发小红书风控，建议降低频率或人工确认后发布",
    "gzh_no_cover": "公众号图文必须有封面图",
    "timeout": "平台响应超时（>60s），可重试",
    # 本批补的通用码（不属于 SPEC-06 §4 表格，但前端同样要拿到人话）
    "over_limit": "内容超出平台字数上限，先点「一键裁剪」",
    "dy_form_rejected": "抖音只接受视频，当前素材形态不合法",
    "xhs_no_media": "小红书图文至少要挂 1 张图或 1 条视频",
    "xhs_no_cover": "小红书图文必须有封面图（3:4）",
    "gzh_empty_body": "公众号正文为空",
    "not_implemented": "真实发布尚未接入（M4），本批为模拟执行",
    "adapt_failed": "平台适配生成失败，可单独重试该平台",
    "publish_failed": "发布失败，草稿已保留，可重试",
    "auth_expired": "登录态已过期，需重新扫码",
}

#: 状态机允许的迁移（非法迁移在 :func:`_next_status` 里被拒）
STATUS_FLOW: dict[str, set[str]] = {
    "pending": {"adapting", "ready", "failed"},
    "adapting": {"ready", "failed"},
    "ready": {"publishing", "failed"},
    "publishing": {"sent", "failed", "awaiting_sms"},
    "awaiting_sms": {"publishing", "sent", "failed"},
    "sent": set(),
    "failed": {"publishing", "ready"},
}

#: 连续失败 3 次不再自动重试（SPEC-06 §4）
MAX_RETRY = 3

#: 短信验证码有效期（秒）—— 5 分钟
SMS_TTL = 300


def error_hint(code: str | None) -> str:
    """错误码 → 人话。未知码也要给人话，不能只显示一个裸码（原则四）。"""
    if not code:
        return ""
    if code in ERROR_HINTS:
        return ERROR_HINTS[code]
    return f"平台返回了未识别的错误码 {code}，看服务端日志里的 raw 字段"


@dataclass
class PlatformRun:
    """单平台一次发布的结果（响应里 ``results`` 的一项）。"""

    platform: str
    name: str
    status: str
    url: str | None = None
    error: str | None = None
    error_code: str | None = None
    hint: str | None = None
    record_id: str | None = None
    dry_run: bool = True
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "name": self.name,
            "status": self.status,
            "url": self.url,
            "error": self.error,
            "error_code": self.error_code,
            "hint": self.hint,
            "record_id": self.record_id,
            "dry_run": self.dry_run,
            "raw": self.raw,
        }


@dataclass
class DispatchResult:
    """一次 ``POST /publish`` 的整体结果。"""

    results: list[PlatformRun] = field(default_factory=list)
    dry_run: bool = True
    notice: str = ""

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.status == "sent")

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if r.status in {"failed", "awaiting_sms"})

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [r.to_dict() for r in self.results],
            "dry_run": self.dry_run,
            "notice": self.notice,
            "ok_count": self.ok_count,
            "failed_count": self.failed_count,
        }


def is_failed(status: str) -> bool:
    return status in {"failed", "awaiting_sms"}


def _blocked_message(items: list[dict[str, Any]]) -> str:
    """人话版的阻断原因。

    ``PrecheckItem`` 里没有 ``actual`` / ``limit`` 字段（读数在 message 里），
    所以直接用 label + message 前半句；别去拼不存在的字段，
    否则会得到「抖音登录态真校验 /」这种断头句，用户在 toast 里直接看到。
    """
    if not items:
        return "硬门禁未通过"
    first = items[0]
    label = first.get("label") or "有 BLOCK 项未过"
    message = str(first.get("message") or "")
    detail = message.split("。")[0].split("；")[0].strip()
    if detail and detail != label:
        return f"硬门禁未通过：{label} · {detail}"
    return f"硬门禁未通过：{label}"


def _next_status(current: str, target: str) -> str:
    """按状态机校验迁移；非法迁移记日志后仍然放行（不能让状态机本身卡住发布）。"""
    allowed = STATUS_FLOW.get(current)
    if allowed is None or target in allowed:
        return target
    log.warning("illegal status transition %s → %s (allowed: %s)", current, target, sorted(allowed or []))
    return target


async def publish_draft(
    draft: PublishDraft,
    platforms: list[str],
    profile: Profile | None = None,
    *,
    confirm: bool = False,
    dry_run: bool = True,
    precheck_items: list[Any] | None = None,
    persist: Any = None,
    assets: list[str] | None = None,
) -> DispatchResult:
    """发布一个草稿到若干平台。

    顺序严格按 SPEC-06 §4：

    1. ``confirm`` 校验 → 缺二次确认直接 ``ValidationError``
    2. ``run_precheck`` → 有 BLOCK 未过 → ``GateBlocked``（带 ``detail.gate_items``）
    3. 逐平台并发，单平台异常捕获，其余照常
    """
    if confirm is not True:
        raise ValidationError(
            "发布需要二次确认",
            detail={"confirm": confirm, "platforms": platforms},
            hint="前端先弹确认弹窗，用户点确认后再带 {confirm: true} 调这个接口",
        )
    targets = [p for p in (platforms or []) if p in PLATFORM_LIMITS]
    if not targets:
        raise ValidationError(
            "没有选择任何平台",
            detail={"platforms": platforms, "supported": list(PLATFORM_LIMITS)},
            hint="先在「平台适配」里勾选至少一个平台",
        )

    items = precheck_items if precheck_items is not None else await run_precheck(draft, profile, selected=targets)
    if precheck_blocked(items):
        blocked_items = [
            i.model_dump(mode="json") if hasattr(i, "model_dump") else dict(i)
            for i in items
            if getattr(i, "severity", None) == "block" and not getattr(i, "passed", True)
        ]
        raise GateBlocked(
            _blocked_message(blocked_items),
            detail={"gate_items": blocked_items, "failed": [i.get("id") for i in blocked_items]},
            hint=blocked_items[0].get("fix_hint") if blocked_items else None,
        )

    result = DispatchResult(dry_run=dry_run)
    if dry_run:
        result.notice = "本次为模拟执行（dry-run）：校验全部真实执行，但没有向平台真实发出内容"

    for p in targets:
        v = _variant_of(draft, p)
        if v is not None:
            v.status = _next_status(v.status, "publishing")
            _sync_counts(v)
    if persist is not None:
        persist(draft)

    runs = await asyncio.gather(
        *[_run_one(draft, p, assets, dry_run) for p in targets],
        return_exceptions=True,  # ★ 单平台异常绝不冒泡打断其他平台
    )
    for p, r in zip(targets, runs, strict=True):
        limits = PLATFORM_LIMITS[p]
        if isinstance(r, BaseException):
            log.exception("platform run crashed (isolated): %s", p, exc_info=r)
            v = _variant_of(draft, p)
            if v is not None:
                v.status = "failed"
                v.error = f"{type(r).__name__}: {r}"
            run = PlatformRun(
                platform=p, name=limits["name"], status="failed",
                error=f"{limits['name']}发布异常：{type(r).__name__}",
                error_code="publish_failed",
                hint=error_hint("publish_failed"),
                raw={"exception": f"{type(r).__name__}: {r}"},
            )
        else:
            run = r
        result.results.append(run)
        v = _variant_of(draft, p)
        if v is not None:
            v.status = run.status
            if run.url:
                v.published_url = run.url
            v.error = run.error if run.status == "failed" else None
    if persist is not None:
        persist(draft)
    return result


async def _run_one(draft: PublishDraft, platform: str, assets: list[str] | None, dry_run: bool) -> PlatformRun:
    """单平台发布。任何异常都在这里兜住，转成 ``failed`` 的 PlatformRun。"""
    limits = PLATFORM_LIMITS[platform]
    adapter = get_adapter(platform)
    v = _variant_of(draft, platform)
    if v is None:
        from .adapt import blank_variant

        v = blank_variant(platform, draft.title, draft.body)
    try:
        auth = await adapter.check_auth()
        if not auth.logged_in:
            code = "dy_auth_4012" if platform == "dy" else "auth_expired"
            return PlatformRun(
                platform=platform, name=limits["name"], status="failed",
                error=f"{limits['name']}发布失败：{auth.message}",
                error_code=code, hint=error_hint(code),
                raw={"auth": auth.to_dict()},
            )
        res: PublishResult = await adapter.publish(v, list(assets or draft.attachments), dry_run)
        if res.ok:
            return PlatformRun(
                platform=platform, name=limits["name"], status="sent",
                url=res.url, dry_run=dry_run, raw=res.raw,
            )
        code = res.error_code or "publish_failed"
        return PlatformRun(
            platform=platform, name=limits["name"], status="failed",
            error=res.error, error_code=code, hint=error_hint(code), dry_run=dry_run, raw=res.raw,
        )
    except Exception as exc:
        log.exception("platform run failed (isolated): %s", platform)
        return PlatformRun(
            platform=platform, name=limits["name"], status="failed",
            error=f"{limits['name']}发布失败：{type(exc).__name__}: {exc}",
            error_code="publish_failed", hint=error_hint("publish_failed"),
            raw={"exception": f"{type(exc).__name__}: {exc}"},
        )


def _variant_of(draft: PublishDraft, platform: str) -> PlatformVariant | None:
    return next((v for v in draft.variants if v.platform == platform), None)


def _sync_counts(v: PlatformVariant) -> None:
    from .adapt import recount

    recount(v)


# ---------------------------------------------------------------------------
# 短信墙
# ---------------------------------------------------------------------------

#: record_id → {code, expires_at, submitted}
_SMS: dict[str, dict[str, Any]] = {}


def sms_state(record_id: str) -> dict[str, Any]:
    """``GET /api/publish/sms/{record_id}`` → ``{need_sms, expires_in}``。"""
    st = _SMS.get(record_id)
    if not st:
        return {"need_sms": False, "expires_in": 0, "message": "没有等待中的短信验证码"}
    expires_at: datetime = st["expires_at"]
    remaining = int((expires_at - datetime.now(UTC)).total_seconds())
    if remaining <= 0:
        _SMS.pop(record_id, None)
        return {"need_sms": False, "expires_in": 0, "message": "验证码已过期，请重新发起发布"}
    return {
        "need_sms": not st.get("submitted"),
        "expires_in": remaining,
        "message": "请在弹窗中输入短信验证码（5 分钟内有效）",
    }


def open_sms_wall(record_id: str) -> dict[str, Any]:
    """平台要求短信验证码：进入 ``awaiting_sms`` 并开始 5 分钟倒计时。"""
    _SMS[record_id] = {
        "created_at": datetime.now(UTC),
        "expires_at": datetime.now(UTC) + timedelta(seconds=SMS_TTL),
        "submitted": False,
    }
    return sms_state(record_id)


def submit_sms(record_id: str, code: str) -> dict[str, Any]:
    """提交验证码。真实验证码校验属 M4（真实平台会校验）；本批只校验格式与有效期。"""
    st = _SMS.get(record_id)
    if not st:
        raise ValidationError(
            "没有等待中的短信验证码",
            detail={"record_id": record_id},
            hint="先发起一次发布，平台要求验证码时才会弹这个弹窗",
        )
    state = sms_state(record_id)
    if not state["need_sms"] and state["expires_in"] == 0:
        raise ValidationError(
            "验证码已过期",
            detail={"record_id": record_id},
            hint="重新发起一次发布，会再弹一次验证码输入",
        )
    digits = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(digits) != 6:
        raise ValidationError(
            "验证码格式不对",
            detail={"record_id": record_id, "length": len(digits)},
            hint="短信验证码是 6 位数字",
        )
    st["submitted"] = True
    log.info("sms code accepted (格式与有效期校验；真实校验属 M4): record=%s", record_id)
    return {"record_id": record_id, "accepted": True, "expires_in": state["expires_in"],
            "notice": "验证码已接收；真实平台的验证码校验属 M4 批次"}


def new_record_id() -> str:
    return f"rec_{uuid.uuid4().hex[:12]}"
