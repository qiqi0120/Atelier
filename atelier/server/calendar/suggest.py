"""SPEC-09 §2 · F-E7 日历建议：窗口内事件 + 画像 → 近 N 天选题 → 整批落池。

- AI 调用**复用** ``topics.service`` 的原语（``run_ai_text`` / ``extract_json`` /
  ``gates_block_or_raise``，SPEC-09 §0 D1）：流式收集、严格 JSON、产出先过门禁，
  BLOCK 整批拒绝——不做静默过滤。
- 落池走 ``create_topic``（source=calendar、due_date=建议日期、
  source_ref=引用的事件名，D3），重复生成不去重（与矩阵同语义）。
- 模型输出违约（日期越窗 / 标题角度假话 / 条数越界）一律 ``AIOutputInvalid``(502)，
  不编造、不截断救场。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from atelier.server.errors import ValidationError
from atelier.server.topics import service as topic_service

from . import service as cal_service
from .service import TITLE_MAX, _to_date  # 同域私有原语：严格 YYYY-MM-DD 校验

__all__ = ["MAX_ITEMS", "SUGGEST_DEFAULT_DAYS", "SUGGEST_MAX_DAYS", "run_suggest"]

#: 建议窗口（天）默认与上限（SPEC-09 §5：days 1..31，默认 14）
SUGGEST_DEFAULT_DAYS = 14
SUGGEST_MAX_DAYS = 31
#: 模型单次最多允许返回的条数（防跑飞；超过视为违约）
MAX_ITEMS = 30
#: 引用事件名长度上限（与事件标题同口径）
_EVENT_REF_MAX = TITLE_MAX
#: 建议角度上限（与选题角度同口径）
_ANGLE_MAX = topic_service.ANGLE_MAX


def build_prompt(start: str, end: str, events: list[dict[str, Any]]) -> str:
    lines = []
    for ev in events:
        suffix = f"：{ev['note']}" if ev["note"] else ""
        lines.append(f"- {ev['date']}（{ev['kind']}）{ev['title']}{suffix}")
    ev_block = "\n".join(lines) if lines else "（窗口内没有日历节点，按画像做通用选题。）"
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    return f"""你在为社交媒体创作者做「日历建议」：结合未来 {days} 天内的日历节点，给出可以直接开工的选题建议。

## 选题时间窗口

{start} 到 {end}（含两端）

## 窗口内的日历节点

{ev_block}

## 你的任务

- 每条建议给出一个适合发布的日期：必须落在窗口内，且尽量贴合相关节点；
- 标题要具体到能直接开工（有对象/有数字/有切口），不要「聊聊XX」「浅谈XX」这类空标题；
- 每条配一句角度说明；event 填引用的节点名，与节点无关的通用建议留空；
- 给 5 到 15 条。

输出**严格 JSON**，不要输出 JSON 以外的任何文字：

{{"items": [{{"date": "YYYY-MM-DD", "title": "不超过80字", "angle": "一句话角度", "event": "节点名或空"}}]}}"""


async def run_suggest(
    *,
    profile_id: str | None = None,
    days: int = SUGGEST_DEFAULT_DAYS,
    today: date | None = None,
) -> dict[str, Any]:
    """生成近 N 天选题建议并整批落池。返回 ``{items, count}``（items 为 topic 形状）。"""
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= SUGGEST_MAX_DAYS:
        raise ValidationError(
            f"days 必须是 1..{SUGGEST_MAX_DAYS} 的整数", detail={"days": days}
        )
    today = today or cal_service.local_today()
    start = today.isoformat()
    end = (today + timedelta(days=days - 1)).isoformat()
    events = cal_service.events_between(start, end)

    # run_ai_text 内部先取画像（不存在 → ProfileNotFound 404），再调模型
    raw = await topic_service.run_ai_text(
        domain="calendar", task="suggest",
        prompt=build_prompt(start, end, events), profile_id=profile_id,
    )
    data = topic_service.extract_json(raw, task="suggest")
    items_raw = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items_raw, list) or not items_raw:
        raise topic_service.AIOutputInvalid(
            "建议输出缺少 items 数组", detail={"task": "suggest", "head": raw[:200]}
        )
    if len(items_raw) > MAX_ITEMS:
        raise topic_service.AIOutputInvalid(
            f"建议返回 {len(items_raw)} 条，超过单次上限 {MAX_ITEMS}",
            detail={"task": "suggest", "count": len(items_raw)},
        )

    parsed: list[dict[str, str]] = []
    for it in items_raw:
        if not isinstance(it, dict):
            raise topic_service.AIOutputInvalid(
                "items 里有非对象元素", detail={"task": "suggest", "item": str(it)[:120]}
            )
        try:
            d = _to_date(it.get("date"), "date")
        except ValidationError as exc:
            # 模型给的日期格式非法属「输出违约」→ 502，不是用户输入错误
            raise topic_service.AIOutputInvalid(
                f"建议日期不是合法的 YYYY-MM-DD：{exc.message}",
                detail={"task": "suggest", "date": str(it.get("date"))[:120]},
            ) from exc
        if not start <= d.isoformat() <= end:
            raise topic_service.AIOutputInvalid(
                f"建议日期 {d.isoformat()} 超出窗口 {start}..{end}",
                detail={"task": "suggest", "date": d.isoformat()},
            )
        title = it.get("title")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > TITLE_MAX:
            raise topic_service.AIOutputInvalid(
                "建议标题为空或超过 80 字", detail={"task": "suggest", "title": str(title)[:120]}
            )
        angle = it.get("angle")
        angle = angle.strip() if isinstance(angle, str) else ""
        if len(angle) > _ANGLE_MAX:
            raise topic_service.AIOutputInvalid(
                f"建议角度超过 {_ANGLE_MAX} 字", detail={"task": "suggest", "angle": angle[:120]}
            )
        event_ref = it.get("event")
        event_ref = event_ref.strip() if isinstance(event_ref, str) else ""
        if len(event_ref) > _EVENT_REF_MAX:
            raise topic_service.AIOutputInvalid(
                "event 引用名超长", detail={"task": "suggest", "event": event_ref[:120]}
            )
        parsed.append({"date": d.isoformat(), "title": title.strip(), "angle": angle, "event": event_ref})

    joined = "\n".join(f"{p['title']}\n{p['angle']}" for p in parsed)
    topic_service.gates_block_or_raise(joined, what="选题建议")

    created = [
        topic_service.create_topic(
            title=p["title"], angle=p["angle"], profile_id=profile_id,
            source="calendar", source_ref=p["event"], due_date=p["date"],
        )
        for p in parsed
    ]
    return {"items": created, "count": len(created)}
