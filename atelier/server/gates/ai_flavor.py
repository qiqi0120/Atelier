"""门禁：AI 味五维打分（**WARN**，低于阈值只告警不阻断）。

维度（SPEC-01 §5）：直接性 / 节奏 / 信任度 / 活人感 / 精炼度。

全部是**确定性启发式**（纯正则 + 统计），不调模型：门禁的价值就在于可复现、
可解释、零成本；PRD 原则二要的是「确定性脚本验收」。

阈值 60。低于阈值产出 WARN 失败项——按 PRD 原则二的分级，软提醒只告警。
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable

from .base import GateInput, GateItem, Severity, ai_item
from .registry import register

__all__ = ["AiFlavorGate", "score_ai_flavor"]

#: 五维权重（合计 1.0）
WEIGHTS: dict[str, float] = {
    "直接性": 0.25,
    "节奏": 0.2,
    "信任度": 0.2,
    "活人感": 0.2,
    "精炼度": 0.15,
}

THRESHOLD = 60

#: 铺垫/总结腔 —— 直接性扣分
_PADDING = (
    "在当今", "随着", "随着……的发展", "众所周知", "不可否认", "毋庸置疑",
    "首先", "其次", "再次", "最后", "总的来说", "总而言之", "综上所述",
    "在……的今天", "让我们", "接下来", "本期", "今天给大家", "hello", "家人们",
)
#: 书面连接词 —— 活人感扣分
_FORMAL = (
    "此外", "因此", "从而", "进而", "与此同时", "换言之", "亦即", "故而",
    "诸如", "综上", "基于此", "鉴于此", "不难看出", "值得注意的是",
)
#: 模糊限定词 —— 信任度扣分
_VAGUE = ("可能", "也许", "大概", "相对而言", "某种程度上", "基本上", "或许", "说不定")
#: 空话 —— 直接性扣分
_EMPTY = ("意义", "价值", "重要性", "值得注意", "具有重要意义", "起到了", "提供了")
#: 口语标记 —— 活人感加分
_COLLOQUIAL = ("我", "你", "咱", "吧", "啊", "嘛", "呢", "哦", "哈", "真的", "其实", "反正", "别", "咋")
#: 停顿/口语连接 —— 活人感加分
_SOFT_SPOKEN = ("挺", "有点", "还", "真的", "就是", "然后", "而且", "不过", "但是", "结果")

_SENT_SPLIT = re.compile(r"[。！？!?\n]+")
_EMPTY_WORDS = ("的", "了", "是", "在", "有", "一个", "我们", "进行", "对于", "以及")
_WS = re.compile(r"\s+")


def _count(hay: str, needles: tuple[str, ...]) -> int:
    return sum(hay.count(n) for n in needles)


def _score_directness(text: str) -> tuple[int, list[str]]:
    hits = _count(text, _PADDING) + _count(text, _EMPTY)
    score = 100 - hits * 14
    reasons = [n for n in _PADDING + _EMPTY if n in text]
    if not text.lstrip():
        reasons.append("内容为空")
    return max(score, 0), reasons


def _score_rhythm(text: str) -> tuple[int, list[str]]:
    sents = [s for s in _SENT_SPLIT.split(text) if s.strip()]
    if len(sents) < 2:
        return 70, []  # 短文没有节奏问题可判，给中性分
    lens = [len(_WS.sub("", s)) for s in sents]
    mean = statistics.fmean(lens)
    spread = statistics.pstdev(lens)
    # 句长有起伏 → 节奏好；全是长句 → 闷
    score = 100 - abs(60 - min(mean, 140)) * 0.35 + min(spread, 18) * 1.6
    if max(lens) > 80:
        score -= 12
    return int(max(min(score, 100), 0)), [f"最长一句 {max(lens)} 字"] if max(lens) > 80 else []


def _score_trust(text: str) -> tuple[int, list[str]]:
    numbers = len(re.findall(r"\d", text))
    specifics = _count(text, _COLLOQUIAL[:3]) + numbers // 4
    vague = _count(text, _VAGUE)
    score = 60 + min(specifics, 20) * 2 - vague * 9
    return int(max(min(score, 100), 0)), [f"{vague} 处模糊限定词"] if vague else []


def _score_human(text: str) -> tuple[int, list[str]]:
    soft = _count(text, _SOFT_SPOKEN)
    formal = _count(text, _FORMAL)
    first_person = text.count("我") + text.count("咱")
    score = 55 + min(soft, 15) * 2.4 + min(first_person, 8) * 1.6 - formal * 11
    if formal:
        return int(max(min(score, 100), 0)), [f"{formal} 处书面连接词"]
    return int(max(min(score, 100), 0)), []


def _score_concise(text: str) -> tuple[int, list[str]]:
    chars = len(_WS.sub("", text))
    if chars == 0:
        return 100, []
    fillers = sum(text.count(w) for w in _EMPTY_WORDS)
    ratio = fillers / max(chars / 10, 1)
    long_tail = max(chars - 300, 0) / 100
    score = 100 - min(ratio, 1.6) * 26 - long_tail * 3
    return int(max(min(score, 100), 0)), [f"虚词密度 {ratio:.1f}"] if ratio > 0.8 else []


_SCORERS: tuple[tuple[str, Callable[[str], tuple[int, list[str]]]], ...] = (
    ("直接性", _score_directness),
    ("节奏", _score_rhythm),
    ("信任度", _score_trust),
    ("活人感", _score_human),
    ("精炼度", _score_concise),
)


def score_ai_flavor(text: str) -> tuple[int, dict[str, int], list[str]]:
    """返回 ``(总分, 各维分, 扣分原因)``。"""
    scores: dict[str, int] = {}
    reasons: list[str] = []
    for name, fn in _SCORERS:
        s, rs = fn(text or "")
        scores[name] = s
        reasons.extend(f"{name}：{r}" for r in rs)
    total = round(sum(scores[k] * w for k, w in WEIGHTS.items()))
    return total, scores, reasons


@register
class AiFlavorGate:
    """AI 味五维打分；低于阈值只告警（WARN），不阻断。"""

    id = "ai_flavor"
    label = "AI 味五维"
    severity = Severity.WARN
    doc = "直接性/节奏/信任度/活人感/精炼度，低于 60 分只告警不阻断"

    def run(self, content: GateInput) -> GateItem:
        text = content.text or ""
        if not text.strip():
            return ai_item(
                gate=self.id,
                label="AI 味五维",
                passed=True,
                actual=None,
                limit=THRESHOLD,
                message="空内容，不判 AI 味",
                fix_hint=None,
                severity=Severity.WARN,
            )
        try:
            total, scores, reasons = score_ai_flavor(text)
        except Exception as exc:  # noqa: BLE001 - 软门禁不阻断，但要留痕
            return ai_item(
                gate=self.id,
                label="AI 味五维（评分异常）",
                passed=True,  # WARN 级不阻断
                actual=f"{type(exc).__name__}",
                limit=THRESHOLD,
                message=f"AI 味打分失败（不影响落盘）：{type(exc).__name__}: {exc}",
                fix_hint="跑 `atelier doctor` 看诊断",
                severity=Severity.WARN,
            )

        detail = " · ".join(f"{k} {v}" for k, v in scores.items())
        passed = total >= THRESHOLD
        if passed:
            return ai_item(
                gate=self.id,
                label="AI 味五维",
                passed=True,
                actual=total,
                limit=THRESHOLD,
                message=f"AI 味 {total}/{THRESHOLD}，通过（{detail}）",
                fix_hint=None,
                severity=Severity.WARN,
            )
        weak = sorted(scores.items(), key=lambda kv: kv[1])[:2]
        return ai_item(
            gate=self.id,
            label="AI 味五维（偏低）",
            passed=False,
            actual=total,
            limit=THRESHOLD,
            message=(
                f"AI 味 {total}/{THRESHOLD}，偏低但不阻断（{detail}）"
                + (f"；主要短板：{'、'.join(f'{k} {v}' for k, v in weak)}" if weak else "")
            ),
            fix_hint=(
                (f"改 {weak[0][0]}：" + "；".join(reasons[:2]) if reasons else "把书面语换成口语，去掉铺垫和总结句")
                if weak
                else "去掉铺垫和总结句，加一句具体细节（数字、时间、亲历）"
            ),
            severity=Severity.WARN,
        )
