"""SPEC-06 §2 · 平台字数（发布域消费层）。

**计数原语在地基层** ``atelier.server.gates.wordcount.count_platform_chars``，
本模块只负责**发布域特有**的部分：把文本裁到平台上限内。

2026-10-02 变更：此前本域自带一份计数实现，门禁 ``gates/wordcount.py`` 另用一套
「非空白字符数」。同一段文字在对话门禁里显示 36、在发布预检里显示 29
（英文标题差 4.8 倍），且门禁会把 20 词的合法英文标题算成 100 字而**错误阻断**。
现把计数原语下沉到地基层并统一口径，本模块改为 import 复用，从构造上杜绝再次漂移。

计数口径（SPEC-06 §2）：中文/日韩 1 字=1 · 英文 1 词=1 · emoji 1 个=2 · 空格标点不计。
"""

from __future__ import annotations

#: 经**模块**引用而非 from-import：``gates.registry.ensure_builtins()`` 会
#: ``importlib.reload`` 内置门禁模块，from-import 会把旧函数对象永久绑死在这里，
#: 导致 reload 后发布域仍在用过期实现（数值静默漂移）。经模块转发可自动跟随。
from ..gates import wordcount as _gates_wc

EMOJI_WEIGHT = _gates_wc.EMOJI_WEIGHT
is_known_platform = _gates_wc.is_known_platform


def count_platform_chars(text: str, platform: str | None = None) -> int:
    """平台字数。转发到地基层唯一实现（SPEC-06 §2 口径）。"""
    return _gates_wc.count_platform_chars(text, platform)


def split_units(text: str) -> list[tuple[str, int]]:
    """把文本切成 ``[(片段, 计数字数), ...]``，供裁剪与逐字渲染复用。"""
    return _gates_wc.split_units(text)


__all__ = [
    "EMOJI_WEIGHT",
    "count_platform_chars",
    "crop_to_limit",
    "is_known_platform",
    "split_units",
]

#: 句读边界：裁剪优先在这些位置断开，砍出来的句子是完整的
_BOUNDARY_CHARS = "。！？!?\n；;｜|"
#: 收尾符：裁完补省略号时，若已带这些就不重复补
_TAIL_CHARS = ("…", "。", "！", "？")


def crop_to_limit(text: str, limit: int) -> tuple[str, int, int]:
    """把文本裁到 ``limit`` 以内，返回 ``(裁剪结果, 原计数, 新计数)``。

    裁剪优先在**句读边界**（。！？!?、换行、分隔符）断开——砍在半句里读起来是残的；
    找不到边界才按原文硬截断并补省略号（省略号是标点，不计入字数）。
    """
    src = text or ""
    units = split_units(src)
    total = sum(w for _, w in units)
    if total <= limit or limit <= 0:
        return src, total, total

    # 按计数单位累加，找到不超过 limit 的最长位置
    used = 0
    kept = 0
    for frag, weight in units:
        if used + weight > limit:
            break
        used += weight
        kept += len(frag)
    cropped = src[:kept].rstrip()

    # 优先落在句读边界，但**不能为了边界把预算浪费大半**——
    # 只在边界位于预算后段（≥ 60%）时才采纳，否则就用能装下的最长截断。
    # 否则 62 字裁到 55 会只留下 21 字，白扔 34 字预算。
    floor = limit * 0.6
    acc = 0
    pos = 0
    boundary = -1
    for frag, weight in units:
        if acc + weight > limit:
            break
        acc += weight
        pos += len(frag)
        tail = src[:pos].rstrip()
        if tail and tail[-1] in _BOUNDARY_CHARS and acc >= floor:
            boundary = pos
    if boundary > 0:
        cropped = src[:boundary].rstrip()

    if not cropped:
        return "", total, 0
    if not cropped.endswith(_TAIL_CHARS):
        cropped += "…"
    return cropped, total, count_platform_chars(cropped)
