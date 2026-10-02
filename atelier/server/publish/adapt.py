"""SPEC-06 §2 · 平台约束表 + 多平台适配流式生成（F-G10）。

三件事：

1. :data:`PLATFORM_LIMITS` —— 三个平台的形态 / 字数上限 / 封面要求（SPEC-06 §2 原文）
2. :func:`build_adapt_prompt` —— 把「平台约束表 + 母版原文 + 画像」拼成 system_prompt
3. :func:`stream_adapt` / :func:`adapt_platforms` —— 每个平台一个 ``harness.stream()``，
   逐字回写 :class:`PlatformVariant`，**一个平台失败不影响其他平台**（SPEC-06 §2 硬要求）

**计数口径不在本模块**：字数一律走 :mod:`atelier.server.publish.wordcount`，
本模块只负责「按哪条上限判」和「生成」。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ..core.models import PlatformVariant, Profile, PublishDraft
from ..harness.base import EventType, TurnRequest
from ..harness.registry import get_harness
from .wordcount import count_platform_chars

log = logging.getLogger("atelier.publish.adapt")

__all__ = [
    "PLATFORM_LIMITS",
    "PLATFORM_ORDER",
    "AdaptEvent",
    "adapt_platforms",
    "build_adapt_prompt",
    "limit_for",
    "platform_meta",
    "recount",
    "stream_adapt",
]

#: SPEC-06 §2 的平台约束表（冻结）
PLATFORM_LIMITS: dict[str, dict[str, Any]] = {
    "xhs": {
        "name": "小红书",
        "forms": ["image", "video"],
        "title_max": 20,
        "body_max": 1000,
        "needs_cover": True,
        "cover_ratio": "3:4",
    },
    "dy": {
        "name": "抖音",
        "forms": ["video"],
        "title_max": 55,
        "body_max": 55,
        "needs_cover": False,
        "cover_ratio": None,
    },
    "gzh": {
        "name": "微信公众号",
        "forms": ["image", "text"],
        "title_max": 64,
        "body_max": 20000,
        "needs_cover": True,
        "cover_ratio": "2.35:1",
    },
}

#: 前端渲染顺序（与原型一致：小红书 / 抖音 / 公众号）
PLATFORM_ORDER: tuple[str, ...] = ("xhs", "dy", "gzh")

#: 各平台适配时给模型的口吻提示（不改变人设，只改表达层）
_TONE: dict[str, str] = {
    "xhs": "小红书口吻：短句 + emoji 分隔 + 结尾留互动问题；保留反常识钩子与具体数字。",
    "dy": "抖音口播标题：一个钩子 + 具体数字，不要长尾从句；正文即口播节奏的短句串。",
    "gzh": "公众号长文：可用小标题分段，开头给结论，结尾留真问题；不要 emoji 堆砌。",
}


def limit_for(platform: str) -> int:
    """该平台**正文字数**上限。"""
    return int(PLATFORM_LIMITS[platform]["body_max"])


def title_limit_for(platform: str) -> int:
    """该平台**标题字数**上限。"""
    return int(PLATFORM_LIMITS[platform]["title_max"])


def platform_meta(platform: str) -> dict[str, Any]:
    """平台元信息（``GET /api/publish/platforms`` 用）。"""
    limits = PLATFORM_LIMITS[platform]
    return {
        "platform": platform,
        "name": limits["name"],
        "forms": list(limits["forms"]),
        "form_label": " / ".join({"image": "图文", "video": "视频", "text": "长文"}[f] for f in limits["forms"]),
        "title_max": limits["title_max"],
        "body_max": limits["body_max"],
        "needs_cover": limits["needs_cover"],
        "cover_ratio": limits["cover_ratio"],
        "constraint": _constraint_text(platform),
    }


def _constraint_text(platform: str) -> str:
    """原型里 `.plat .sub` 那一行约束说明。"""
    limits = PLATFORM_LIMITS[platform]
    parts = ["/".join({"image": "图文", "video": "视频", "text": "长文"}[f] for f in limits["forms"])]
    if limits["needs_cover"]:
        parts.append(f"需封面图（{limits['cover_ratio']}）")
    parts.append(f"正文 ≤ {limits['body_max']} 字")
    parts.append(f"标题 ≤ {limits['title_max']} 字")
    return " · ".join(parts)


def recount(variant: PlatformVariant) -> PlatformVariant:
    """按本域口径重算字数与超限标记（SPEC-06 §2 的读数唯一来源）。"""
    limit = limit_for(variant.platform)
    variant.char_limit = limit
    variant.char_count = count_platform_chars(variant.body, variant.platform)
    variant.over_limit = variant.char_count > limit
    return variant


def blank_variant(platform: str, title: str = "", body: str = "") -> PlatformVariant:
    """新建一个未适配的 variant（母版选定平台时用）。"""
    v = PlatformVariant(
        platform=platform,  # type: ignore[arg-type]
        title=title,
        body=body,
        char_count=0,
        char_limit=limit_for(platform),
        over_limit=False,
        adapted=False,
        status="pending",
    )
    return recount(v)


def build_adapt_prompt(draft: PublishDraft, platforms: list[str], profile: Profile | None) -> str:
    """SPEC-06 §2：system_prompt 里给「平台约束表 + 母版原文 + 画像」。"""
    lines: list[str] = [
        "你是这个账号的写作助手。任务：把下面这份「母版」适配成多个平台的版本。",
        "",
        "## 母版原文（唯一事实来源，不要编造新事实/新数据）",
        f"标题：{draft.title}",
        "正文：",
        draft.body,
    ]
    if draft.topic_tags:
        lines += ["", "话题标签：" + " ".join(f"#{t}" for t in draft.topic_tags)]

    lines += ["", "## 本次要适配的平台与硬约束"]
    for p in platforms:
        limits = PLATFORM_LIMITS[p]
        lines.append(
            f"- {p}（{limits['name']}）：形态 {'/'.join(limits['forms'])}；"
            f"正文 ≤ {limits['body_max']} 字；标题 ≤ {limits['title_max']} 字。"
            f"{_TONE[p]}"
        )
    lines += [
        "",
        "## 计数口径（必须自己遵守）",
        "中文/日韩字 1 字 = 1；英文 1 词 = 1；emoji 1 个 = 2；空格与标点不计。",
        "超限会被硬门禁拦住，务必压在上限内。",
    ]

    if profile is not None and not profile.general_mode:
        lines += [
            "",
            "## 账号画像（人设不可改写，只能换平台表达）",
            f"定位：{profile.identity}",
            f"风格：{profile.style}",
            f"受众：{profile.audience}",
            f"平台约束：{profile.platform_rules}",
            f"偏好红线：{profile.preferences}",
        ]
    else:
        lines += ["", "## 账号画像", "通用模式：没有注入画像，保持中性口吻。"]

    lines += [
        "",
        "## 输出格式（严格照做）",
        "只输出正文，不要写「好的」「以下是」这类开场，也不要写 markdown 代码块。",
        "每个平台单独一段，段首写一行 `##平台: xhs` 这样的标记，然后是该平台的正文。",
    ]
    return "\n".join(lines)


class AdaptEvent(dict):
    """适配流事件。**刻意做成 dict 子类**：SSE 序列化时直接 ``dict(e)``。"""

    @property
    def platform(self) -> str:
        return str(self.get("platform") or "")


async def stream_adapt(
    draft: PublishDraft,
    platform: str,
    profile: Profile | None,
    *,
    title: str = "",
) -> AsyncIterator[AdaptEvent]:
    """单个平台的适配流。逐 ``text_delta`` 产出事件，末尾 ``done`` 一次。

    失败**不抛给调用方**：产出 ``error`` 事件后正常收尾，这样
    :func:`adapt_platforms` 里其他平台的并发流不受影响（SPEC-06 §2）。
    """
    turn_id = f"adapt-{platform}-{uuid.uuid4().hex[:8]}"
    # session_id 带平台名：同一草稿多平台并发时 MockHarness 的「一个 session 一个活跃
    # turn」约束不会互相踩（PRD F-B12）
    req = TurnRequest(
        session_id=f"publish-{draft.id}-{platform}",
        turn_id=turn_id,
        prompt=f"请按 system 里的平台约束适配母版，先输出 {platform}。",
        profile=profile,
        system_suffix=build_adapt_prompt(draft, [platform], profile),
        project=draft.project,
    )
    body: list[str] = []
    thinking: list[str] = []
    harness = get_harness()
    try:
        async for ev in harness.stream(req):
            if ev.type == EventType.THINKING_DELTA:
                t = ev.text()
                if t:
                    thinking.append(t)
                    yield AdaptEvent(type="thinking", platform=platform, text=t, turn_id=turn_id)
            elif ev.type == EventType.TEXT_DELTA:
                t = ev.text()
                if t:
                    body.append(t)
                    yield AdaptEvent(type="delta", platform=platform, text=t, turn_id=turn_id)
            elif ev.type == EventType.ERROR:
                yield AdaptEvent(
                    type="error", platform=platform, turn_id=turn_id,
                    message=str(ev.data.get("message") or "适配生成失败"),
                    error_code="adapt_failed",
                )
            elif ev.type == EventType.DONE:
                break
    except Exception as exc:
        log.exception("adapt failed: platform=%s draft=%s", platform, draft.id)
        yield AdaptEvent(
            type="error", platform=platform, turn_id=turn_id,
            message=f"{PLATFORM_LIMITS[platform]['name']}适配失败：{type(exc).__name__}",
            error_code="adapt_failed",
        )
        return

    text = _strip_markers("".join(body), platform)
    yield AdaptEvent(
        type="done", platform=platform, turn_id=turn_id,
        title=title, body=text, char_count=count_platform_chars(text, platform),
        char_limit=limit_for(platform), thinking="".join(thinking),
    )


def _strip_markers(text: str, platform: str) -> str:
    """去掉模型可能带上的 ``##平台: xhs`` 分隔标记与代码块围栏。

    适配输出会直接进字数门禁，标记残留会被算进字数，所以这里必须洗一遍。
    """
    out_lines: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("```"):
            continue
        if s.startswith("#") and ":" in s and "平台" in s:
            continue
        if s in {"##平台:" + platform, f"##平台: {platform}"}:
            continue
        out_lines.append(line)
    cleaned = "\n".join(out_lines).strip()
    # 只留本平台那一段（模型偶尔会把多平台写在一起）
    if "##平台:" in cleaned:
        head, _, tail = cleaned.partition(f"##平台: {platform}")
        picked = tail if tail.strip() else head
        parts = picked.split("##平台:")
        cleaned = parts[0].strip()
    return cleaned


async def adapt_platforms(
    draft: PublishDraft,
    platforms: list[str],
    profile: Profile | None,
) -> AsyncIterator[AdaptEvent]:
    """并发适配多个平台，**逐字**产出事件（F-G10 前端逐字渲染）。

    单平台失败隔离：某个平台的流抛异常或产出 ``error`` 事件时只记它自己的
    ``failed``，其余平台的流继续跑到底（SPEC-06 §2 硬要求）。

    产出：``thinking`` / ``delta``（带 ``text`` 与累计 ``acc``）/ ``done``（带完整
    ``variant``）/ ``error``，最后一条 ``summary`` 汇总本轮成功与失败。
    """
    wanted = [p for p in platforms if p in PLATFORM_LIMITS]
    if not wanted:
        return

    queue: asyncio.Queue[AdaptEvent | None] = asyncio.Queue()

    async def run(platform: str) -> None:
        acc: list[str] = []
        try:
            async for ev in stream_adapt(draft, platform, profile, title=draft.title):
                kind = ev.get("type")
                if kind == "delta":
                    acc.append(str(ev.get("text") or ""))
                    await queue.put(AdaptEvent(type="delta", platform=platform, text=ev.get("text"), acc="".join(acc)))
                elif kind == "thinking":
                    await queue.put(ev)
                elif kind == "done":
                    await queue.put(AdaptEvent(type="variant", platform=platform, variant=_make_variant(
                        platform, str(ev.get("title") or draft.title), str(ev.get("body") or "")
                    )))
                elif kind == "error":
                    await queue.put(AdaptEvent(type="error", platform=platform, message=ev.get("message")))
        except Exception as exc:
            log.exception("adapt task crashed: platform=%s draft=%s", platform, draft.id)
            await queue.put(AdaptEvent(
                type="error", platform=platform,
                message=f"{PLATFORM_LIMITS[platform]['name']}适配失败：{type(exc).__name__}",
                error_code="adapt_failed",
            ))
        finally:
            await queue.put(None)  # 本平台结束

    tasks = [asyncio.create_task(run(p)) for p in wanted]
    finished = 0
    ok: list[str] = []
    failed: dict[str, str] = {}
    try:
        while finished < len(tasks):
            ev = await queue.get()
            if ev is None:
                finished += 1
                continue
            if ev.get("type") == "variant":
                ok.append(str(ev.get("platform")))
            elif ev.get("type") == "error":
                failed[str(ev.get("platform"))] = str(ev.get("message") or "适配失败")
            yield ev
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()

    yield AdaptEvent(type="summary", ok=ok, failed=failed)



def _make_variant(platform: str, title: str, body: str) -> PlatformVariant:
    v = PlatformVariant(
        platform=platform,  # type: ignore[arg-type]
        title=title,
        body=body,
        char_count=0,
        char_limit=limit_for(platform),
        over_limit=False,
        adapted=True,
        status="ready",
    )
    return recount(v)
