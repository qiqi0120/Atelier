"""SPEC-08 §2/§3 · F-E9 选题评分：7 维打分 + 确定性结论。

结论（做/不做/改方向）**由代码按总分判定**，不由模型自报（SPEC-08 §0 D3）——
模型只给分和理由，verdict 是算出来的，所以三档阈值可以直接测。
每次评分**追加**一条 ``topic_scores``（保留历史），回读走最新一条。
"""

from __future__ import annotations

import uuid
from typing import Any

from ..core import db
from . import service
from .service import AIOutputInvalid

__all__ = ["DIMENSIONS", "DONT_THRESHOLD", "DO_THRESHOLD", "SCORE_MAX", "SCORE_MIN", "run_score"]

#: 7 维（键冻结；risk 语义反向：5 分 = 低风险）。中文序见 SPEC-08 §3。
DIMENSIONS: dict[str, str] = {
    "traffic": "流量潜力",
    "match": "账号匹配",
    "differentiation": "竞争差异化",
    "timing": "时效",
    "monetization": "变现",
    "cost": "成本",
    "risk": "风险（5 = 低风险）",
}

SCORE_MIN, SCORE_MAX = 1, 5
#: verdict 阈值（SPEC-08 §3 冻结）：total ≥ 27 做，≤ 18 不做，其余改方向
DO_THRESHOLD = 27
DONT_THRESHOLD = 18


def verdict_for(total: int) -> str:
    """确定性判定：do / pivot / dont。分数越界由调用方先拦。"""
    if total >= DO_THRESHOLD:
        return "do"
    if total <= DONT_THRESHOLD:
        return "dont"
    return "pivot"


def _validate_dims(raw: Any, *, task: str = "score") -> dict[str, int]:
    """7 维齐全、每维 1..5 的整数（bool 不算整数）——缺/多/越界都是模型违约。"""
    if not isinstance(raw, dict):
        raise AIOutputInvalid("评分输出缺少 dims 对象", detail={"task": task, "head": str(raw)[:200]})
    dims: dict[str, int] = {}
    for key in DIMENSIONS:
        val = raw.get(key)
        if isinstance(val, bool) or not isinstance(val, int) or not SCORE_MIN <= val <= SCORE_MAX:
            raise AIOutputInvalid(
                f"维度 {key} 缺失或不是 {SCORE_MIN}..{SCORE_MAX} 的整数",
                detail={"task": task, "dims": raw},
                hint="重试一次；模型需要按约定输出 7 维整数分",
            )
        dims[key] = val
    return dims


def build_prompt(topic: dict[str, Any]) -> str:
    dims_desc = "、".join(f"{key}（{label}）" for key, label in DIMENSIONS.items())
    angle = topic["angle"] or "（未填角度）"
    ref = topic["source_ref"] or "无"
    return f"""你在为社交媒体创作者评估一个选题值不值得做。只依据给定信息判断，不编造数据。

## 选题

- 标题：{topic["title"]}
- 备注角度：{angle}
- 来源：{topic["source"]}（{ref}）

## 你的任务

按 7 个维度打分，每维 1–5 整数（5 = 该维表现最好；风险维 5 分 = 风险最低）：
{dims_desc}

输出**严格 JSON**，不要输出 JSON 以外的任何文字（包括代码围栏说明）：

{{"dims": {{"traffic": 整数, "match": 整数, "differentiation": 整数, "timing": 整数, "monetization": 整数, "cost": 整数, "risk": 整数}}, "reason": "一句话说清最高与最低分的理由，给出可执行的建议方向"}}

「做 / 不做 / 改方向」的结论不用你给，工作台会按总分判定。"""


async def run_score(*, topic_id: str, profile_id: str | None = None) -> dict[str, Any]:
    """给已入库的选题打分并**追加**一条评分历史。"""
    topic = service.get_topic(topic_id)  # 不存在 → NotFound(404)
    raw = await service.run_ai_text(
        task="score", prompt=build_prompt(topic), profile_id=profile_id
    )
    data = service.extract_json(raw, task="score")
    if not isinstance(data, dict):
        raise AIOutputInvalid("评分输出不是 JSON 对象", detail={"task": "score", "head": raw[:200]})
    dims = _validate_dims(data.get("dims"))
    total = sum(dims.values())
    verdict = verdict_for(total)
    reason = str(data.get("reason") or "").strip()[:300]
    sid = f"tscore-{uuid.uuid4().hex[:16]}"
    created = db.utcnow()
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO topic_scores (id, topic_id, dims, total, verdict, reason, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (sid, topic_id, db.dumps(dims), total, verdict, reason, created),
        )
    return {
        "id": sid,
        "topic_id": topic_id,
        "title": topic["title"],
        "dims": dims,
        "total": total,
        "verdict": verdict,
        "reason": reason,
        "created_at": created,
    }
