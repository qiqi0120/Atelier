"""SPEC-15 §2 · 归因域四个 AI 任务：评论洞察 / 内容复盘 / 爆款预测 / 策略建议。

全部复用 ``topics.service`` 原语（``run_ai_text(domain="attribution")`` /
``extract_json`` / ``gates_block_or_raise``，SPEC-15 §0 D3），诚实模式是硬要求：

- 数据不足 → ``{insufficient: true, need, message}`` **不调模型**（D1）；
- AI 只解读代码算出的统计，prompt 明写「不要编数字」；
- 缺段 → ``AttributionIncomplete``(422)，模型输出违约 → ``AIOutputInvalid``(502)；
- 产出先过门禁，BLOCK 即 ``GateBlocked``；除复盘沉淀（用户显式勾选）外不落库。

段落/列表校验助手复用 ``insights.service``（与 SPEC-11/12 同一口径，不重复实现）。
"""

from __future__ import annotations

import json
from typing import Any

from atelier.server.errors import ValidationError
from atelier.server.insights.service import (
    ITEM_MAX,
    parse_markdown_sections,
    validate_str_list,
)
from atelier.server.topics import service as topic_service

from . import service

__all__ = [
    "COMMENT_MIN",
    "PREDICT_NOTICE",
    "REVIEW_SECTIONS",
    "STRATEGY_SECTIONS",
    "VERDICT_VALUES",
    "run_comments_insight",
    "run_predict",
    "run_review",
    "run_strategy",
]

#: F-G32 评论洞察的最低语料（不足 422 且不调模型）
COMMENT_MIN = 30
THEMES_MAX = 6
COUNT_HINT_MAX = 20
QUOTE_MAX = 80
NAME_MAX = 40
FACTORS_MAX = 5
VERDICT_VALUES: tuple[str, ...] = ("试试", "改后发", "放弃")

#: F-G35 响应固定诚实标注（SPEC-15 §0 D6，不许删改）
PREDICT_NOTICE = "预测是参考性质（P3），基于文本特征与通用经验，不保证实际表现"

REVIEW_SECTIONS: tuple[str, ...] = ("有效结构", "受众偏好", "失效做法", "下一步")
STRATEGY_SECTIONS: tuple[str, ...] = ("保持", "调整", "停止")


def _insufficient(stats: dict[str, Any], need: int, message: str) -> dict[str, Any]:
    return {"insufficient": True, "stats": stats, "need": need, "message": message}


# ---------------------------------------------------------------------------
# F-G32 评论洞察（用户粘贴评论 → AI 提取高频反馈；不落库）
# ---------------------------------------------------------------------------

_COMMENTS_PROMPT = """你在为社交媒体创作者分析评论区反馈。下面是用户从平台手工复制粘贴的评论原文，
它是你唯一的数据来源，**原文里没有的反馈不要编造**。

## 评论原文

{text}

## 你的任务

基于以上原文，输出**严格 JSON**，不要输出 JSON 以外的任何文字：

{{"themes": [{{"theme": "高频主题（≤80字）", "count_hint": "近似计数", "sample_quote": "一条原话摘录（≤80字）"}}],
  "requests": ["观众的具体诉求（1 到 {req_max} 条，每条 ≤{item_max} 字）"],
  "sentiment": {{"positive": 非负数, "negative": 非负数, "neutral": 非负数}}}}

- **count_hint 是用户粘贴内容里的近似计数，你不得虚构精确数字**；数不出来就写
  「少量 / 多条 / 约一半」这类模糊描述，绝不输出看似精确的统计
- themes 1 到 {th_max} 条；sentiment 三个值口径保持一致（都是条数或都是占比）"""


async def run_comments_insight(*, text: str, profile_id: str | None = None) -> dict[str, Any]:
    if not isinstance(text, str) or len(text.strip()) < COMMENT_MIN:
        got = len(text.strip()) if isinstance(text, str) else 0
        raise ValidationError(
            f"评论文本至少 {COMMENT_MIN} 字（当前 {got} 字）",
            detail={"min": COMMENT_MIN, "got": got},
            hint="从平台 App 全选复制评论再粘贴进来；语料太少不做洞察、不编结论",
        )
    raw = await topic_service.run_ai_text(
        domain="attribution", task="comments-insight",
        prompt=_COMMENTS_PROMPT.format(
            text=text.strip(), req_max=THEMES_MAX, item_max=ITEM_MAX, th_max=THEMES_MAX
        ),
        profile_id=profile_id,
    )
    data = topic_service.extract_json(raw, task="comments-insight")
    if not isinstance(data, dict):
        raise topic_service.AIOutputInvalid(
            "评论洞察的输出不是 JSON 对象",
            detail={"task": "comments-insight", "head": raw[:200]},
        )

    themes_raw = data.get("themes")
    if not isinstance(themes_raw, list) or not themes_raw:
        raise topic_service.AIOutputInvalid(
            "评论洞察输出缺 themes 数组", detail={"task": "comments-insight", "head": raw[:200]}
        )
    if len(themes_raw) > THEMES_MAX:
        raise topic_service.AIOutputInvalid(
            f"themes 返回 {len(themes_raw)} 条，超过上限 {THEMES_MAX}",
            detail={"task": "comments-insight", "count": len(themes_raw)},
        )
    themes: list[dict[str, str]] = []
    for it in themes_raw:
        if not isinstance(it, dict):
            raise topic_service.AIOutputInvalid(
                "themes 里有非对象元素", detail={"task": "comments-insight", "item": str(it)[:120]}
            )
        theme = it.get("theme")
        if not isinstance(theme, str) or not (2 <= len(theme.strip()) <= ITEM_MAX):
            raise topic_service.AIOutputInvalid(
                f"theme 缺失或超过 {ITEM_MAX} 字", detail={"task": "comments-insight", "got": str(theme)[:80]}
            )
        hint_raw = it.get("count_hint")
        count_hint = str(hint_raw).strip() if isinstance(hint_raw, (str, int)) and not isinstance(hint_raw, bool) else ""
        if not count_hint or len(count_hint) > COUNT_HINT_MAX:
            raise topic_service.AIOutputInvalid(
                f"count_hint 缺失或超过 {COUNT_HINT_MAX} 字（必须是粘贴内容里的近似计数）",
                detail={"task": "comments-insight", "got": str(hint_raw)[:80]},
            )
        quote = it.get("sample_quote")
        if not isinstance(quote, str) or not (1 <= len(quote.strip()) <= QUOTE_MAX):
            raise topic_service.AIOutputInvalid(
                f"sample_quote 缺失或超过 {QUOTE_MAX} 字", detail={"task": "comments-insight", "got": str(quote)[:80]}
            )
        themes.append({"theme": theme.strip(), "count_hint": count_hint, "sample_quote": quote.strip()})

    requests = validate_str_list(data.get("requests"), label="requests",
                                 max_items=THEMES_MAX, max_len=ITEM_MAX)

    sentiment_raw = data.get("sentiment")
    if not isinstance(sentiment_raw, dict) or set(sentiment_raw) != {"positive", "negative", "neutral"}:
        raise topic_service.AIOutputInvalid(
            "sentiment 必须是含 positive/negative/neutral 三个键的对象",
            detail={"task": "comments-insight", "got": str(sentiment_raw)[:120]},
        )
    sentiment: dict[str, float] = {}
    for k, v in sentiment_raw.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            raise topic_service.AIOutputInvalid(
                f"sentiment.{k} 必须是非负数", detail={"task": "comments-insight", "got": str(v)[:60]}
            )
        sentiment[k] = v

    gate_report = topic_service.gates_block_or_raise(
        "\n".join(f"{t['theme']}（{t['count_hint']}）：{t['sample_quote']}" for t in themes)
        + "\n" + "\n".join(requests),
        what="评论洞察",
    )
    return {
        "themes": themes,
        "requests": requests,
        "sentiment": sentiment,
        "notice": "count_hint 是用户粘贴内容里的近似计数，非平台精确统计",
        "gate_report": gate_report,
    }


# ---------------------------------------------------------------------------
# F-G33 内容复盘（本地 stats → AI 解读 → 恰 4 段；可沉淀进画像）
# ---------------------------------------------------------------------------

_REVIEW_PROMPT = """你在为社交媒体创作者做内容复盘。以下数据是**系统从本地记录统计的客观事实**，
你只做解读，不要自己编数字、不要质疑数据来源。

## 客观 stats（代码统计）

{stats_block}

## 你的任务

基于以上事实，输出 Markdown，**恰好 4 个 `##` 段**，段名必须含这些关键词、顺序不许变：

1. `## 有效结构` — 数据撑得住的选题/格式，引用 stats 里的具体数字
2. `## 受众偏好` — 从表现与选题流转里读出的受众信号
3. `## 失效做法` — 该停的动作；数据撑不出结论就如实写「数据不足以下判断」
4. `## 下一步` — 2~4 条可执行动作

不要输出这 4 段以外的前言、结语或解释。{profile_line}"""


async def run_review(
    *, profile_id: str | None = None, sediment: bool = False
) -> dict[str, Any]:
    stats = service.collect_review_stats()
    if stats["records_total"] < service.RECORDS_FOR_REVIEW:
        return _insufficient(
            stats,
            service.RECORDS_FOR_REVIEW,
            f"发布满 {service.RECORDS_FOR_REVIEW} 条后才有复盘"
            f"（当前 {stats['records_total']} 条）——复盘只解读真实记录",
        )

    profile_line = (
        "复盘口径对齐注入的创作者画像。"
        if profile_id
        else "当前没有画像，是通用复盘；结尾用一句话如实标注「未挂画像，结论未沉淀」。"
    )
    raw = await topic_service.run_ai_text(
        domain="attribution", task="review",
        prompt=_REVIEW_PROMPT.format(
            stats_block=json.dumps(stats, ensure_ascii=False, indent=2), profile_line=profile_line
        ),
        profile_id=profile_id,
    )
    sections = parse_markdown_sections(raw, REVIEW_SECTIONS)
    missing = [kw for kw, ok in sections.items() if not ok]
    if missing:
        raise service.AttributionIncomplete(
            f"复盘结果缺段：{'、'.join(missing)}",
            detail={"missing": missing, "expected": list(REVIEW_SECTIONS)},
        )
    gate_report = topic_service.gates_block_or_raise(raw, what="内容复盘")

    result: dict[str, Any] = {
        "insufficient": False,
        "stats": stats,
        "markdown": raw,
        "sections": sections,
        "gate_report": gate_report,
        "profile_used": bool(profile_id),
        "sedimented": False,
        "memory_id": None,
    }
    if sediment and profile_id:
        # 沉淀在门禁之后：BLOCK 已在上面抛出，不会把没过门禁的文本写进画像
        result.update(service.sediment_memory(profile_id, raw))
    elif not profile_id:
        result["notice"] = "未挂画像：本次为通用复盘，要点未写入任何画像长期记忆"
    return result


# ---------------------------------------------------------------------------
# F-G35 爆款预测（P3，参考性质；不落库）
# ---------------------------------------------------------------------------

_PREDICT_PROMPT = """你在为社交媒体创作者做发布前的爆款预测（P3 参考性质）。

## 待发布内容

- 平台：{platform}
- 标题：{title}
- 正文：
{body}

## 你的任务

基于文本特征（钩子强度、具体性、情绪、结构）与通用平台经验，输出**严格 JSON**，
不要输出 JSON 以外的任何文字：

{{"score": 0 到 100 的整数,
  "factors": [{{"name": "因素名（≤{name_max}字）", "impact": "该因素如何影响分数（≤{item_max}字）"}}],
  "verdict": "试试 | 改后发 | 放弃"}}

- factors 1 到 {factors_max} 条，impact 要指向标题/正文里的具体位置，不要空泛
- score 是参考性打分，不是承诺；verdict 只允许三选一"""


async def run_predict(
    *, title: str, body: str, platform: str, profile_id: str | None = None
) -> dict[str, Any]:
    if not isinstance(title, str) or not title.strip():
        raise ValidationError("标题不能为空", hint="把要发布的标题贴进来再预测")
    if len(title.strip()) > 120:
        raise ValidationError("标题最长 120 字", detail={"max": 120})
    if not isinstance(body, str) or not body.strip():
        raise ValidationError("正文不能为空", hint="把要发布的正文贴进来再预测")
    if not isinstance(platform, str) or not platform.strip():
        raise ValidationError("platform 不能为空", hint="预测必须指明目标平台")
    raw = await topic_service.run_ai_text(
        domain="attribution", task="predict",
        prompt=_PREDICT_PROMPT.format(
            platform=platform.strip(), title=title.strip(), body=body.strip(),
            name_max=NAME_MAX, item_max=ITEM_MAX, factors_max=FACTORS_MAX,
        ),
        profile_id=profile_id,
    )
    data = topic_service.extract_json(raw, task="predict")
    if not isinstance(data, dict):
        raise topic_service.AIOutputInvalid(
            "预测的输出不是 JSON 对象", detail={"task": "predict", "head": raw[:200]}
        )
    score = data.get("score")
    if isinstance(score, bool) or not isinstance(score, int) or not (0 <= score <= 100):
        raise topic_service.AIOutputInvalid(
            f"score 必须是 0-100 的整数（当前 {score!r}）",
            detail={"task": "predict", "score": str(score)[:60]},
        )
    factors_raw = data.get("factors")
    if not isinstance(factors_raw, list) or not (1 <= len(factors_raw) <= FACTORS_MAX):
        raise topic_service.AIOutputInvalid(
            f"factors 必须是 1 到 {FACTORS_MAX} 条（当前 {len(factors_raw) if isinstance(factors_raw, list) else '非数组'}）",
            detail={"task": "predict", "count": str(len(factors_raw))[:20]},
        )
    factors: list[dict[str, str]] = []
    for it in factors_raw:
        if not isinstance(it, dict):
            raise topic_service.AIOutputInvalid(
                "factors 里有非对象元素", detail={"task": "predict", "item": str(it)[:120]}
            )
        name, impact = it.get("name"), it.get("impact")
        if not isinstance(name, str) or not (2 <= len(name.strip()) <= NAME_MAX):
            raise topic_service.AIOutputInvalid(
                f"因素名缺失或超过 {NAME_MAX} 字", detail={"task": "predict", "got": str(name)[:80]}
            )
        if not isinstance(impact, str) or not (2 <= len(impact.strip()) <= ITEM_MAX):
            raise topic_service.AIOutputInvalid(
                f"impact 缺失或超过 {ITEM_MAX} 字", detail={"task": "predict", "got": str(impact)[:80]}
            )
        factors.append({"name": name.strip(), "impact": impact.strip()})
    verdict = data.get("verdict")
    if verdict not in VERDICT_VALUES:
        raise topic_service.AIOutputInvalid(
            f"verdict 只允许 {' / '.join(VERDICT_VALUES)}（当前 {verdict!r}）",
            detail={"task": "predict", "verdict": str(verdict)[:60]},
        )

    gate_report = topic_service.gates_block_or_raise(
        "\n".join(f"{f['name']}：{f['impact']}" for f in factors) + f"\n结论：{verdict}",
        what="爆款预测",
    )
    return {
        "score": score,
        "factors": factors,
        "verdict": verdict,
        "notice": PREDICT_NOTICE,
        "gate_report": gate_report,
    }


# ---------------------------------------------------------------------------
# F-G36 策略建议（历史聚合 → AI 解读 → 恰 3 段；不落库）
# ---------------------------------------------------------------------------

_STRATEGY_PROMPT = """你在为社交媒体创作者给下一步策略建议。以下数据是**系统从本地记录聚合的客观事实**，
你只做解读，不要自己编数字、不要质疑数据来源。

## 历史聚合（代码统计，近 {window} 天）

{stats_block}

## 你的任务

基于以上事实，输出 Markdown，**恰好 3 个 `##` 段**，段名必须含这些关键词、顺序不许变：

1. `## 保持` — 数据证明有效的动作，引用具体数字
2. `## 调整` — 值得改的环节与改法
3. `## 停止` — 该停的动作；数据撑不出结论就如实写「数据不足以下判断」

不要输出这 3 段以外的前言、结语或解释。{profile_line}"""


async def run_strategy(*, profile_id: str | None = None) -> dict[str, Any]:
    stats = service.strategy_stats()
    if stats["metrics_total"] == 0 and stats["records_total"] < service.RECORDS_FOR_STRATEGY:
        return _insufficient(
            stats,
            service.RECORDS_FOR_STRATEGY,
            "还没有任何表现数据，且发布记录不足 3 条"
            f"（记录 {stats['records_total']} 条 / 表现 {stats['metrics_total']} 条）——"
            "策略建议只基于真实历史，不空谈",
        )

    profile_line = (
        "建议口径对齐注入的创作者画像。"
        if profile_id
        else "当前没有画像，给通用创作者口径的建议。"
    )
    raw = await topic_service.run_ai_text(
        domain="attribution", task="strategy",
        prompt=_STRATEGY_PROMPT.format(
            window=stats["window_days"],
            stats_block=json.dumps(stats, ensure_ascii=False, indent=2),
            profile_line=profile_line,
        ),
        profile_id=profile_id,
    )
    sections = parse_markdown_sections(raw, STRATEGY_SECTIONS)
    missing = [kw for kw, ok in sections.items() if not ok]
    if missing:
        raise service.AttributionIncomplete(
            f"策略建议缺段：{'、'.join(missing)}",
            detail={"missing": missing, "expected": list(STRATEGY_SECTIONS)},
        )
    gate_report = topic_service.gates_block_or_raise(raw, what="策略建议")
    return {"insufficient": False, "stats": stats, "markdown": raw, "sections": sections,
            "gate_report": gate_report}
