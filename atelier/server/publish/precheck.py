"""SPEC-06 §3 · 发布前预检（F-G12 / F-G13）。

**分级是本模块唯一不可让步的语义**：

===================================  ======  ==================================
检查                                 分级    失败时
===================================  ======  ==================================
合规风险扫描                          BLOCK    阻断，给出命中的词与位置
各平台字数                            BLOCK    标红 + 「一键裁剪」按钮
封面图                               BLOCK    阻断，提示去内容库挂载
登录态                               BLOCK    提示去登录中心
出站密钥扫描                          BLOCK    fail-closed 阻断
标题打分                             WARN     告警 + 给改写建议
人设一致性                           WARN     ★ 仅提醒，绝不阻断（F-G13）
时机建议                             WARN     告警
===================================  ======  ==================================

``blocked = any(item.severity is BLOCK and not item.passed)``。

**F-G13 是硬验收项**：人设不一致时必须仍能发布。因此
:func:`_persona_item` 无论判定多不一致，``severity`` 恒为 ``WARN``，
且 :func:`precheck_blocked` 只看 BLOCK 级。
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from ..core.models import PlatformVariant, PrecheckItem, Profile, PublishDraft
from ..gates.base import GateInput, Severity
from ..gates.registry import run_gates
from .adapt import PLATFORM_LIMITS
from .platforms import get_adapter
from .wordcount import count_platform_chars

log = logging.getLogger("atelier.publish.precheck")

__all__ = [
    "CHECK_LABELS",
    "precheck_blocked",
    "run_precheck",
    "score_title",
]

#: 预检项 id → 中文标签（前端分组用）
CHECK_LABELS: dict[str, str] = {
    "compliance": "合规风险扫描",
    "wordcount": "平台字数",
    "cover": "封面图",
    "auth": "登录态",
    "secret_scan": "出站密钥扫描",
    "title_score": "标题打分",
    "persona": "人设一致性（软提醒，不阻断）",
    "timing": "时机建议",
}


def precheck_blocked(items: list[PrecheckItem]) -> bool:
    """只有 **BLOCK 级未通过** 才算阻断。WARN（含人设一致性）一律不阻断。"""
    return any(i.severity == Severity.BLOCK and not i.passed for i in items)


async def run_precheck(
    draft: PublishDraft,
    profile: Profile | None = None,
    *,
    auth_states: dict[str, Any] | None = None,
    selected: list[str] | None = None,
) -> list[PrecheckItem]:
    """跑全部预检项。``selected`` 为空时按草稿里已适配的 variant 判定。"""
    variants = _targets(draft, selected)
    texts = _all_texts(draft, variants)
    items: list[PrecheckItem] = []

    items.extend(_compliance_items(draft, texts))
    items.extend(_wordcount_items(variants))
    items.extend(await _cover_items(variants, draft))
    items.extend(await _auth_items(variants, auth_states))
    items.append(_secret_scan_item(texts))
    items.append(_title_score_item(draft))
    items.append(_persona_item(draft, profile, variants))
    items.append(_timing_item(variants))
    return items


# ---------------------------------------------------------------------------
# 目标与文本
# ---------------------------------------------------------------------------


def _targets(draft: PublishDraft, selected: list[str] | None) -> list[PlatformVariant]:
    """本次要判的 variant。

    ``selected`` 优先：用户勾了但还没适配的平台也要判（此时拿母版当它的正文判字数）。
    """
    if not selected:
        return list(draft.variants)
    from .adapt import blank_variant

    by_key = {v.platform: v for v in draft.variants}
    return [by_key.get(p) or blank_variant(p, draft.title, draft.body) for p in selected]



def _all_texts(draft: PublishDraft, variants: list[PlatformVariant]) -> str:
    """出站文本全集：母版 + 各平台版本（合规/密钥扫描要全覆盖）。"""
    parts = [draft.title, draft.body]
    for v in variants:
        parts += [v.title, v.body]
    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# 1. 合规风险扫描（BLOCK，复用 gates/compliance.py）
# ---------------------------------------------------------------------------


def _compliance_items(draft: PublishDraft, texts: str) -> list[PrecheckItem]:
    report = run_gates(GateInput.of(texts, title=draft.title), ["compliance"])
    item = next(i for i in report.items if i.gate == "compliance")
    if item.passed:
        return [
            PrecheckItem(
                id="compliance", label=CHECK_LABELS["compliance"], severity=Severity.BLOCK,
                passed=True, message="极限词 0 · 医疗功效 0 · 违禁品 0",
            )
        ]
    from ..gates.compliance import scan_compliance

    hits = scan_compliance(texts, draft.title)
    detail = "；".join(f"{h['category']}「{h['term']}」（{h['where']}）" for h in hits[:5])
    return [
        PrecheckItem(
            id="compliance", label=CHECK_LABELS["compliance"], severity=Severity.BLOCK,
            passed=False, message=f"命中 {len(hits)} 处风险词：{detail}",
            fix_hint="改掉上面标出的词再发；极限词按广告法不能出现在推广内容里",
        )
    ]


# ---------------------------------------------------------------------------
# 2. 各平台字数（BLOCK）
# ---------------------------------------------------------------------------


def _wordcount_items(variants: list[PlatformVariant]) -> list[PrecheckItem]:
    """逐平台字数。★ 计数走本域 :mod:`wordcount`，**不在前端重复实现**（SPEC-06 §2）。

    抖音标题与正文同限 55，原型读数取**标题**（61/55）；但正文同样受 55 约束，
    所以**标题与正文任一超限都算未过**——只判标题会出现「预检说过了、adapter
    发布时又报超限」的自相矛盾（SPEC-06 §3 与 §5 的判定必须一致）。
    """
    out: list[PrecheckItem] = []
    for v in variants:
        limits = PLATFORM_LIMITS[v.platform]
        limit = int(limits["body_max"])
        body_actual = count_platform_chars(v.body, v.platform)
        title_actual = count_platform_chars(v.title, v.platform)
        title_limit = int(limits["title_max"])
        body_over = body_actual > limit
        title_over = title_actual > title_limit

        if v.platform == "dy":
            actual, what = title_actual, "标题"  # 读数取标题（与原型一致）
        else:
            actual, what = body_actual, "正文"
        over = body_over or title_over  # 任一超限都拦

        name = limits["name"]
        if over:
            label = f"{name}{what}超字数（硬门禁）"
            if v.platform == "dy" and title_over and body_over:
                msg = (
                    f"标题 {title_actual} / {title_limit} 字，正文 {body_actual} / {limit} 字。"
                    f"点「一键裁剪」自动压到上限内。"
                )
            elif v.platform == "dy" and body_over:
                msg = f"标题 {title_actual} / {title_limit} 字没问题，但正文 {body_actual} / {limit} 字超限。点「一键裁剪」。"
            else:
                msg = (
                    f"{actual} / {limit if what == '正文' else title_limit} 字。"
                    f"裁掉末尾 {actual - (limit if what == '正文' else title_limit)} 个字即可，"
                    f"或点「一键裁剪」自动压到上限内。"
                )
        else:
            label = f"{name}{what}字数"
            msg = f"{actual} / {limit if what == '正文' else title_limit} 字，在上限内"
        out.append(
            PrecheckItem(
                id=f"wordcount:{v.platform}",
                label=label,
                severity=Severity.BLOCK,
                passed=not over,
                message=msg,
                fix_hint="点「一键裁剪」自动压到上限内" if over else None,
                platform=v.platform,
            )
        )
    return out


# ---------------------------------------------------------------------------
# 3. 封面图（BLOCK）
# ---------------------------------------------------------------------------


async def _cover_items(variants: list[PlatformVariant], draft: PublishDraft) -> list[PrecheckItem]:
    from .platforms.base import cover_ok

    out: list[PrecheckItem] = []
    for v in variants:
        limits = PLATFORM_LIMITS[v.platform]
        if not limits["needs_cover"]:
            continue
        ratio = limits["cover_ratio"]
        ok, detail = cover_ok(list(draft.attachments), ratio)
        name = limits["name"]
        out.append(
            PrecheckItem(
                id=f"cover:{v.platform}",
                label=f"{name}封面图",
                severity=Severity.BLOCK,
                passed=ok,
                message=(f"已挂载 {detail}" + (f" · 符合{name} {ratio}" if ok else "")) if ok
                else f"{detail}。{name}必须有封面图且比例 {ratio}",
                fix_hint="到内容库挂一张封面图再回来" if not ok else None,
                platform=v.platform,
            )
        )
    return out


# ---------------------------------------------------------------------------
# 4. 登录态（BLOCK，真校验）
# ---------------------------------------------------------------------------


async def _auth_items(
    variants: list[PlatformVariant], auth_states: dict[str, Any] | None
) -> list[PrecheckItem]:
    out: list[PrecheckItem] = []
    for v in variants:
        if auth_states is not None and v.platform in auth_states:
            st = auth_states[v.platform]
        else:
            st = await get_adapter(v.platform).check_auth()
        name = PLATFORM_LIMITS[v.platform]["name"]
        out.append(
            PrecheckItem(
                id=f"auth:{v.platform}",
                label=f"{name}登录态真校验",
                severity=Severity.BLOCK,
                passed=bool(st.logged_in),
                message=str(st.message),
                fix_hint=None if st.logged_in else "到「账号登录」扫码后再发",
                platform=v.platform,
            )
        )
    return out


# ---------------------------------------------------------------------------
# 5. 出站密钥扫描（BLOCK，fail-closed）
# ---------------------------------------------------------------------------


def _secret_scan_item(texts: str) -> PrecheckItem:
    """复用 ``gates/secret_scan.py``。它自身 fail-closed（扫描器异常按命中处理）。"""
    report = run_gates(GateInput.of(texts), ["secret_scan"])
    item = next(i for i in report.items if i.gate == "secret_scan")
    return PrecheckItem(
        id="secret_scan", label=CHECK_LABELS["secret_scan"], severity=Severity.BLOCK,
        passed=item.passed, message=item.message, fix_hint=item.fix_hint,
    )


# ---------------------------------------------------------------------------
# 6. 标题打分（WARN）
# ---------------------------------------------------------------------------

_HOOKS = ("为什么", "怎么", "居然", "竟然", "别再", "后悔", "真相", "原来", "3 个", "第一", "别","?", "？")
_SEARCHABLE = ("AI", "工作流", "效率", "工具", "内容", "创作", "Agent", "自动化", "提示词", "复盘")


def score_title(title: str) -> tuple[float, float, float, str]:
    """标题三项打分 0–10：钩子 / 具体度 / 搜索词命中。确定性启发式（不调模型）。"""
    t = (title or "").strip()
    if not t:
        return 0.0, 0.0, 0.0, "标题为空"
    hook = min(10.0, sum(2.0 for h in _HOOKS if h in t))
    digits = len(re.findall(r"\d", t))
    specificity = min(10.0, digits * 1.5 + (2.0 if any(c in t for c in "：:｜|，,。") else 0.0))
    hits = [k for k in _SEARCHABLE if k.lower() in t.lower()]
    search = min(10.0, len(hits) * 2.5)
    note = "、".join(hits) if hits else "未命中常见搜索词"
    return hook, specificity, search, note


def _title_score_item(draft: PublishDraft) -> PrecheckItem:
    hook, spec, search, note = score_title(draft.title)
    total = (hook + spec + search) / 3
    passed = total >= 6.0
    if passed:
        message = f"钩子 {hook:.1f} / 具体度 {spec:.1f} / 搜索词命中 {search:.1f}（{note}）"
    else:
        msg = f"钩子 {hook:.1f} / 具体度 {spec:.1f} / 搜索词命中 {search:.1f}（{note}）。"
        if search < 6:
            msg += "标题里补一个可被搜到的词（如 AI 工作流 / 内容创作）。"
        if hook < 6:
            msg += "开头加个钩子（为什么 / 别再 / 居然）。"
        message = msg
    return PrecheckItem(
        id="title_score", label=CHECK_LABELS["title_score"], severity=Severity.WARN,
        passed=passed, message=message,
        fix_hint=None if passed else "按上面的建议改标题；这条只告警，不拦发布",
    )


# ---------------------------------------------------------------------------
# 7. 人设一致性（WARN，★ 绝不阻断 —— F-G13）
# ---------------------------------------------------------------------------

_VAGUE_TONE = ("赋能", "闭环", "抓手", "颗粒度", "打法", "心智", "势能", "生态位")
_FIRST_PERSON = ("我", "我的", "我把", "我试", "我踩")


def _persona_item(
    draft: PublishDraft, profile: Profile | None, variants: list[PlatformVariant]
) -> PrecheckItem:
    """对照画像 ``style`` + ``preferences`` 给人设一致性判断。

    ★ **无论判定多不一致，severity 恒为 WARN**（F-G13 硬要求：不一致只提醒，绝不阻断）。
    文案里显式写「软提醒，不阻断」，让用户知道这条拦不住他。
    """
    text = _all_texts(draft, variants)
    if profile is None or profile.general_mode:
        return PrecheckItem(
            id="persona", label=CHECK_LABELS["persona"], severity=Severity.WARN,
            passed=True, message="通用模式：未注入画像，跳过人设一致性检查",
        )
    if not (profile.style.strip() or profile.preferences.strip()):
        return PrecheckItem(
            id="persona", label=CHECK_LABELS["persona"], severity=Severity.WARN,
            passed=True, message="画像的风格与偏好红线都还没填，无法判断一致性",
            fix_hint="到「账号画像」补齐风格与偏好红线，这项检查才有意义",
        )

    reasons: list[str] = []
    style = profile.style
    prefs = profile.preferences

    vague_hits = [w for w in _VAGUE_TONE if w in text]
    if vague_hits and not any(w in (style + prefs) for w in vague_hits):
        reasons.append(f"正文出现 {len(vague_hits)} 处黑话（{'、'.join(vague_hits[:3])}），画像里没有这些表达")

    first_person = sum(text.count(w) for w in _FIRST_PERSON)
    if first_person == 0 and ("真" in style or "亲测" in style or "实测" in style):
        reasons.append("画像要求写真实经历（实测/亲测），但正文通篇没有第一人称")

    if "emoji" in style.lower() or "表情" in style:
        emoji_here = any(ord(ch) > 0x1F000 for ch in text)
        if not emoji_here:
            reasons.append("画像风格提到可以用 emoji，但正文没有用到")

    if not reasons:
        return PrecheckItem(
            id="persona", label=CHECK_LABELS["persona"], severity=Severity.WARN,
            passed=True,
            message=f"与画像「{profile.name}」的风格与偏好红线一致，可发",
        )
    return PrecheckItem(
        id="persona", label=CHECK_LABELS["persona"], severity=Severity.WARN,  # ★ 恒 WARN
        passed=False,
        message="；".join(reasons) + "。（软提醒，不阻断——你确认没问题就可以发）",
        fix_hint="想更贴人设可以改一版；不想改也完全可以直接发",
    )


# ---------------------------------------------------------------------------
# 8. 时机建议（WARN）
# ---------------------------------------------------------------------------

_GOOD_HOURS = {
    "xhs": {8, 12, 13, 19, 20, 21, 22},
    "dy": {7, 8, 12, 13, 18, 19, 20, 21},
    "gzh": {7, 8, 20, 21, 22},
}


def _timing_item(variants: list[PlatformVariant]) -> PrecheckItem:
    hour = datetime.now(UTC).astimezone().hour  # 本地钟点：发布时机是给人看的，按用户所在时区判断
    names = [PLATFORM_LIMITS[v.platform]["name"] for v in variants]
    good = [n for n, v in ((PLATFORM_LIMITS[x.platform]["name"], x) for x in variants)
            if hour in _GOOD_HOURS.get(v.platform, set())]
    if not names:
        return PrecheckItem(
            id="timing", label=CHECK_LABELS["timing"], severity=Severity.WARN,
            passed=True, message="还没选平台，暂不判断发布时机",
        )
    if good:
        return PrecheckItem(
            id="timing", label=CHECK_LABELS["timing"], severity=Severity.WARN,
            passed=True, message=f"{hour:02d}:00 是 {'、'.join(good)} 的活跃时段，适合现在发",
        )
    return PrecheckItem(
        id="timing", label=CHECK_LABELS["timing"], severity=Severity.WARN,
        passed=False,
        message=f"{hour:02d}:00 不在 {'、'.join(names)} 的活跃时段（常见活跃：早 7–9 / 午 12–13 / 晚 18–22）",
        fix_hint="可以现在发，也可以用「排期发布」挪到晚上；这条只告警",
    )
