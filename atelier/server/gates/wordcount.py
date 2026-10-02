"""门禁：各平台字数上限（BLOCK）。

SPEC-01 §5 给的上限：小红书 1000 / 抖音标题 55 / 公众号 20000。

**两处 spec 空白，本实现按「从严」处理并在此标注（待 spec 确认）：**

1. ``platform`` 为 None 时用哪个上限？→ 用最严的小红书 1000，并在 label 里
   写明「未指定平台，按小红书 1000 字从严」，避免静默放行。
2. 抖音给了标题上限 55，但没说正文上限；本实现对「有平台无标题」的情况也用
   1000 兜底（见 ``_FALLBACK_LIMIT``）。

计数口径：**本模块持有全项目唯一的字数计数原语** ``count_platform_chars``
（中文 1 字=1 / 英文 1 词=1 / emoji 1 个=2 / 空格标点不计，SPEC-06 §2）。

2026-10-02 合并说明：此前本门禁用「非空白字符数」``count_chars``，而发布预检用
「平台口径」``count_platform_chars``，同一段文字会显示两个不同数字（英文标题差 4.8 倍），
且门禁会把 20 词的合法英文标题算成 100 字而错误阻断。现已统一到平台口径：
地基层持有原语，发布域 import 复用，从构造上保证两处读数一致。
``count_chars`` 保留为兼容别名，内部转调新口径。
"""

from __future__ import annotations

import re
import unicodedata

from .base import GateInput, GateItem, Severity, ai_item
from .registry import register

__all__ = [
    "EMOJI_WEIGHT",
    "PLATFORM_LIMITS",
    "WordCountGate",
    "count_chars",
    "count_platform_chars",
    "split_units",
]

#: 平台 → 上限字符数（SPEC-01 §5 冻结）
PLATFORM_LIMITS: dict[str, int] = {
    "xhs": 1000,  # 小红书正文
    "dy": 55,  # 抖音标题
    "gzh": 20000,  # 公众号正文
}

#: 无标题/无平台时的从严兜底上限（见模块 docstring）
_FALLBACK_LIMIT = 1000

EMOJI_WEIGHT = 2

# CJK / 假名 / 谚文 / 全角（含扩展 A 与兼容表意文字）
_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x1100, 0x11FF),    # 谚文字母
    (0x2E80, 0x2EFF),    # 康熙部首补充
    (0x3000, 0x303F),    # CJK 标点（其中标点类会被标点规则先滤掉）
    (0x3040, 0x30FF),    # 平假名 / 片假名
    (0x3130, 0x318F),    # 谚文兼容字母
    (0x3400, 0x4DBF),    # 扩展 A
    (0x4E00, 0x9FFF),    # 基本区
    (0xA960, 0xA97F),    # 谚文扩展 A
    (0xAC00, 0xD7FF),    # 谚文音节
    (0xF900, 0xFAFF),    # 兼容表意文字
    (0xFF00, 0xFF60),    # 全角形式
    (0x20000, 0x2A6DF),  # 扩展 B
)

# emoji / 象形符号区段（不含普通几何图形，避免把 ○ ◆ 当 emoji）
_EMOJI_RANGES: tuple[tuple[int, int], ...] = (
    (0x231A, 0x231B),    # ⌚⌛
    (0x23E9, 0x23EC),
    (0x25AA, 0x25AB),
    (0x25B6, 0x25B6),
    (0x25C0, 0x25C0),
    (0x25FB, 0x25FE),
    (0x2600, 0x27BF),    # 杂项符号 + 装饰符号
    (0x2934, 0x2935),
    (0x2B00, 0x2BFF),    # 箭头补充（部分平台算符号）
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3299),
    (0x1F000, 0x1FAFF),  # 主要 emoji 区
    (0x1F1E6, 0x1F1FF),  # 区域指示符（国旗）
)

# emoji 内部修饰：变体选择符 / ZWJ / 肤色修饰 —— 不单独计
_EMOJI_MODIFIERS: frozenset[int] = frozenset(
    {0xFE0E, 0xFE0F, 0x200D, 0x20E3, *range(0x1F3FB, 0x1F400)}
)

# 数字并入「词」：2026 算 1
_WORD_EXTRA: frozenset[int] = frozenset(
    {0x2019, 0x2018, 0x0027, 0x2010, 0x2011, 0x2013, 0x2014}  # 词内撇号/连字符
)


def _in(ranges: tuple[tuple[int, int], ...], cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in ranges)


def _is_punct(ch: str) -> bool:
    """标点（Unicode 类别 P*）不计。``#`` 属于 Po，所以话题标签不算字数。"""
    return unicodedata.category(ch).startswith("P")


def _is_word_char(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return cat.startswith(("L", "N")) or ord(ch) in _WORD_EXTRA


def is_known_platform(platform: str | None) -> bool:
    """是否是我们有字数规则的平台。未知平台不报错，按默认规则计数。"""
    return (platform or "").strip().lower() in PLATFORM_LIMITS


def _is_regional(ch: str) -> bool:
    return 0x1F1E6 <= ord(ch) <= 0x1F1FF


def _units_with_pos(text: str) -> list[tuple[str, int, int]]:
    """同 :func:`split_units`，但每项多带一个「在原文里的结束下标」。

    裁剪必须按**原文切片**，不能把片段 join 起来——那样会把原文的空格吃掉，
    裁出来的句子读起来是粘在一起的。
    """
    out: list[tuple[str, int, int]] = []
    src = text or ""
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        cp = ord(ch)
        if ch.isspace() or _is_punct(ch):
            i += 1
            continue
        if cp in _EMOJI_MODIFIERS:
            i += 1  # 只在 emoji 内部作为修饰出现，独立出现不计
            continue
        if _in(_EMOJI_RANGES, cp):
            j = i + 1
            joined = False  # 上一个字符是不是 ZWJ（决定后面还能不能接一个 emoji）
            while j < n:
                cj = ord(src[j])
                if cj in _EMOJI_MODIFIERS:
                    joined = cj == 0x200D
                    j += 1
                    continue
                if _in(_EMOJI_RANGES, cj) and (joined or _is_regional(src[j])):
                    joined = False
                    j += 1
                    continue
                break
            out.append((src[i:j], EMOJI_WEIGHT, j))
            i = j
            continue
        # CJK / 假名 / 谚文：逐字计 1（且不并入英文词）
        if _in(_CJK_RANGES, cp) and unicodedata.category(ch)[0] in ("L", "N"):
            out.append((ch, 1, i + 1))
            i += 1
            continue
        if _is_word_char(ch):
            j = i
            while j < n:
                c2 = src[j]
                if c2.isspace() or _is_punct(c2) or ord(c2) in _EMOJI_MODIFIERS:
                    break
                if _in(_CJK_RANGES, ord(c2)) or _in(_EMOJI_RANGES, ord(c2)):
                    break
                if _is_word_char(c2):
                    j += 1
                    continue
                break
            if j == i:
                j = i + 1
            out.append((src[i:j], 1, j))
            i = j
            continue
        i += 1  # 其他符号（数学/货币等）不计
    return out


def split_units(text: str) -> list[tuple[str, int]]:
    """把文本切成 ``[(片段, 计数字数), ...]``。

    供前端「逐字渲染」与裁剪复用：一个片段就是一个计数单位（CJK 单字 /
    英文单词 / 1 个 emoji 记 2）。空片段不产出。
    """
    return [(frag, weight) for frag, weight, _ in _units_with_pos(text)]


def count_platform_chars(text: str, platform: str | None = None) -> int:
    """SPEC-06 §2 的平台字数。``platform`` 保留给将来分平台差异化，当前三平台同规则。"""
    return sum(w for _, w, _ in _units_with_pos(text))


_WS = re.compile(r"\s+")


def count_chars(text: str) -> int:
    """**兼容别名**，等价于 :func:`count_platform_chars`。

    保留是因为门禁的历史测试与外部调用都引用它；语义已统一到平台口径。
    新代码请直接用 ``count_platform_chars``。
    """
    return count_platform_chars(text)


@register
class WordCountGate:
    """按平台判字数上限，超了阻断。"""

    id = "wordcount"
    label = "平台字数上限"
    severity = Severity.BLOCK
    doc = "小红书 1000 / 抖音标题 55 / 公众号 20000 字，超限即阻断"

    def run(self, content: GateInput) -> GateItem:
        platform = (content.platform or "").strip().lower()

        # 抖音限的是标题：优先按标题判
        if platform == "dy" and content.title:
            return self._check(content.title, platform="dy", limit=PLATFORM_LIMITS["dy"], what="标题")

        if platform in PLATFORM_LIMITS:
            limit = PLATFORM_LIMITS[platform]
            what = "标题" if content.title and PLATFORM_LIMITS.get("dy") == limit else "正文"
            return self._check(content.text, platform=platform, limit=limit, what=what)

        if platform:
            # 未知平台：不阻断，但要说清没按谁判
            return ai_item(
                gate=self.id,
                label=f"{platform} 字数",
                passed=True,
                actual=count_platform_chars(content.text),
                limit=None,
                message=f"没有 {platform} 的字数规则，本次未判字数",
                fix_hint=None,
            )

        # 没指定平台 → 从严
        return self._check(content.text, platform="", limit=_FALLBACK_LIMIT, what="正文（未指定平台，从严）")

    def _check(self, text: str, *, platform: str, limit: int, what: str) -> GateItem:
        actual = count_chars(text)
        passed = actual <= limit
        name = {"xhs": "小红书", "dy": "抖音", "gzh": "公众号"}.get(platform, platform or "正文")
        if platform == "dy":
            label = f"抖音{what}字数"
        elif platform:
            label = f"{name}{what}字数"
        else:
            label = "正文字数（未指定平台）"
        return ai_item(
            gate=self.id,
            label=label,
            passed=passed,
            actual=actual,
            limit=limit,
            message=(
                f"{label} {actual}/{limit} 字，通过"
                if passed
                else f"{what} {actual} 字，超出 {name or '平台'} 上限 {limit} 字，超了 {actual - limit} 字"
            ),
            fix_hint=None if passed else f"删掉 {actual - limit} 字；或用「一键裁剪」自动压到上限内",
        )
