"""SPEC-14 §0 D5 · F-G19 平台优化建议（AI 工具，不落库）。

输出严格 JSON：``{titles[1..3], tags[1..6], timing, notes[1..3]}``。
复用 ``topics.service`` 原语（domain="publish"），越界 ``AIOutputInvalid``(502)，
门禁 BLOCK 422。
"""

from __future__ import annotations

from typing import Any

from atelier.server.topics import service as topic_service

__all__ = ["OPTIMIZE_LIMITS", "run_optimize"]

OPTIMIZE_LIMITS: dict[str, Any] = {
    "titles": {"max": 3, "len": 40},
    "tags": {"max": 6, "len": 20},
    "timing": {"len": 120},
    "notes": {"max": 3, "len": 100},
}

_PROMPT = """你在为社交媒体创作者优化一条即将发布的内容。平台：{platform}。{profile_line}

## 待优化内容

标题：{title}

正文：
{body}

## 你的任务

输出严格 JSON，不要输出 JSON 以外的任何文字：

```json
{{"titles": ["优化后的标题（≤{title_len}字，含原意但更抓人）"],
  "tags": ["该平台常用话题标签（不带#号）"],
  "timing": "发布时机建议（该平台的高流量时段+为什么，≤{timing_len}字）",
  "notes": ["发布前要注意的平台特性/风控提醒"]}}
```

约束：titles 1~{title_max} 条且每条 ≤{title_len} 字；tags 1~{tag_max} 个每个 ≤{tag_len} 字；
notes 1~{note_max} 条每条 ≤{note_len} 字。建议必须贴合该平台的真实特性（字数上限、口吻、
流量机制），不确定的机制写「待验证」，不编造平台规则。"""


def _validate(data: Any) -> dict[str, Any]:
    limits = OPTIMIZE_LIMITS
    if not isinstance(data, dict):
        raise topic_service.AIOutputInvalid("优化建议不是 JSON 对象", detail={"got": str(data)[:120]})
    titles = data.get("titles")
    if not isinstance(titles, list) or not 1 <= len(titles) <= limits["titles"]["max"]:
        raise topic_service.AIOutputInvalid(
            f"titles 缺失或超过 {limits['titles']['max']} 条", detail={"got": str(titles)[:120]}
        )
    titles = [str(t).strip() for t in titles]
    if any(not t or len(t) > limits["titles"]["len"] for t in titles):
        raise topic_service.AIOutputInvalid(
            f"titles 里有空项或超过 {limits['titles']['len']} 字", detail={"titles": titles}
        )
    tags = data.get("tags")
    if not isinstance(tags, list) or not 1 <= len(tags) <= limits["tags"]["max"]:
        raise topic_service.AIOutputInvalid(
            f"tags 缺失或超过 {limits['tags']['max']} 个", detail={"got": str(tags)[:120]}
        )
    tags = [str(t).strip().lstrip("#") for t in tags]
    if any(not t or len(t) > limits["tags"]["len"] for t in tags):
        raise topic_service.AIOutputInvalid(
            f"tags 里有空项或超过 {limits['tags']['len']} 字", detail={"tags": tags}
        )
    timing = str(data.get("timing") or "").strip()
    if not timing or len(timing) > limits["timing"]["len"]:
        raise topic_service.AIOutputInvalid(
            f"timing 缺失或超过 {limits['timing']['len']} 字", detail={"timing": timing[:120]}
        )
    notes = data.get("notes")
    if not isinstance(notes, list) or not 1 <= len(notes) <= limits["notes"]["max"]:
        raise topic_service.AIOutputInvalid(
            f"notes 缺失或超过 {limits['notes']['max']} 条", detail={"got": str(notes)[:120]}
        )
    notes = [str(n).strip() for n in notes]
    if any(not n or len(n) > limits["notes"]["len"] for n in notes):
        raise topic_service.AIOutputInvalid(
            f"notes 里有空项或超过 {limits['notes']['len']} 字", detail={"notes": notes}
        )
    return {"titles": titles, "tags": tags, "timing": timing, "notes": notes}


async def run_optimize(
    *, platform: str, title: str, body: str, profile_id: str | None = None
) -> dict[str, Any]:
    profile_line = (
        "结合注入的创作者画像（定位/风格）给建议。"
        if profile_id
        else "当前是通用模式、没有画像，先说明这一点。"
    )
    prompt = _PROMPT.format(
        platform=platform,
        profile_line=profile_line,
        title=title or "（无标题）",
        body=(body or "")[:4000],
        title_len=OPTIMIZE_LIMITS["titles"]["len"],
        title_max=OPTIMIZE_LIMITS["titles"]["max"],
        tag_max=OPTIMIZE_LIMITS["tags"]["max"],
        tag_len=OPTIMIZE_LIMITS["tags"]["len"],
        timing_len=OPTIMIZE_LIMITS["timing"]["len"],
        note_max=OPTIMIZE_LIMITS["notes"]["max"],
        note_len=OPTIMIZE_LIMITS["notes"]["len"],
    )
    raw = await topic_service.run_ai_text(
        domain="publish", task="optimize", prompt=prompt, profile_id=profile_id
    )
    data = topic_service.extract_json(raw, task="optimize")
    result = _validate(data)
    serialized = __import__("json").dumps(result, ensure_ascii=False)
    gate_report = topic_service.gates_block_or_raise(serialized, what="平台优化建议")
    return {"platform": platform, **result, "gate_report": gate_report}
