"""SPEC-08 §2/§4 · F-E11 标题 Hook：多变体开头钩子 + 逐条字数校验。

字数口径**只此一家**：:func:`gates.wordcount.count_platform_chars`
（PLAN-M2 §2 复用提醒——M1 曾因门禁与预检两套字数口径踩过坑）。
platform 缺省按 ``dy``（55 字）从严：钩子本质是标题；给了未知平台则 422，
不假装校验过。
"""

from __future__ import annotations

import re
from typing import Any

from ..gates.wordcount import PLATFORM_LIMITS, count_platform_chars
from . import service
from .service import AIOutputInvalid, ValidationError

__all__ = ["DEFAULT_PLATFORM", "MAX_VARIANTS", "run_hooks"]

#: platform 缺省时的从严口径（SPEC-08 §4）
DEFAULT_PLATFORM = "dy"
#: 变体数量护栏：模型约定 3–5 条，超出视为违约
MIN_VARIANTS, MAX_VARIANTS = 3, 8
#: 单条变体长度上限（防跑飞；超长本身会被字数判定如实标 FAIL）
VARIANT_MAX = 200

_VARIANT_RE = re.compile(r"\s+")


def limit_for(platform: str) -> tuple[str, int]:
    """平台 → ``(归一化平台名, 字数上限)``。未知平台 422，不静默放行。"""
    p = (platform or "").strip().lower()
    if not p:
        return DEFAULT_PLATFORM, PLATFORM_LIMITS[DEFAULT_PLATFORM]
    if p not in PLATFORM_LIMITS:
        raise ValidationError(
            f"没有 {p} 的字数规则",
            detail={"platform": p, "known": sorted(PLATFORM_LIMITS)},
            hint="当前支持：" + " / ".join(sorted(PLATFORM_LIMITS)) + "；不传 platform 则按抖音标题 55 字从严",
        )
    return p, PLATFORM_LIMITS[p]


def build_prompt(title: str, *, platform: str, angle: str = "") -> str:
    angle_block = f"\n- 备注角度：{angle}" if angle else ""
    return f"""你在为社交媒体创作者生成标题/开头钩子的多变体。钩子要让人在 1 秒内想点进来：
具体、有切口、不空喊；可以混用「反常识结论 / 数字承诺 / 提问 / 身份代入」等开头法。

## 选题

- 标题：{title}{angle_block}
- 目标平台：{platform}

## 你的任务

生成 3–5 条钩子变体，每条 ≤ 55 字（抖音标题口径），彼此开头法不同。

输出**严格 JSON**，不要输出 JSON 以外的任何文字：

{{"variants": [{{"text": "钩子文本"}}]}}"""


async def run_hooks(
    *,
    topic_id: str | None = None,
    title: str | None = None,
    platform: str = "",
    profile_id: str | None = None,
) -> dict[str, Any]:
    """生成钩子变体。**不落库**——选用哪条由用户决定，应用走 PATCH /topics/{id}。"""
    angle = ""
    if topic_id:
        topic = service.get_topic(topic_id)  # 不存在 → 404
        title = topic["title"]
        angle = topic["angle"]
    if not title or not str(title).strip():
        raise ValidationError(
            "需要 title 或已存在的 topic_id 之一",
            detail={"title": title, "topic_id": topic_id},
            hint="直接给标题，或先在选题库里选一条",
        )
    t = service.validate_title(title)
    plat, limit = limit_for(platform)

    raw = await service.run_ai_text(
        task="hooks", prompt=build_prompt(t, platform=plat, angle=angle), profile_id=profile_id
    )
    data = service.extract_json(raw, task="hooks")
    variants_raw = data.get("variants") if isinstance(data, dict) else None
    if not isinstance(variants_raw, list) or not variants_raw:
        raise AIOutputInvalid("钩子输出缺少 variants 数组", detail={"task": "hooks", "head": raw[:200]})
    if not MIN_VARIANTS <= len(variants_raw) <= MAX_VARIANTS:
        raise AIOutputInvalid(
            f"钩子变体应为 {MIN_VARIANTS}–{MAX_VARIANTS} 条，实际 {len(variants_raw)} 条",
            detail={"task": "hooks", "count": len(variants_raw)},
        )
    texts: list[str] = []
    for v in variants_raw:
        text = str(v.get("text") if isinstance(v, dict) else v or "").strip()
        if not text:
            raise AIOutputInvalid("钩子变体里有空文本", detail={"task": "hooks"})
        if len(text) > VARIANT_MAX:
            raise AIOutputInvalid(
                f"钩子变体超过 {VARIANT_MAX} 字，视为违约输出",
                detail={"task": "hooks", "head": text[:60]},
            )
        texts.append(_VARIANT_RE.sub(" ", text))

    gate_report = service.gates_block_or_raise("\n".join(texts), what="钩子变体")
    variants = [
        {
            "text": text,
            "chars": count_platform_chars(text),
            "limit": limit,
            "passed": count_platform_chars(text) <= limit,
        }
        for text in texts
    ]
    return {"variants": variants, "gate_report": gate_report}
