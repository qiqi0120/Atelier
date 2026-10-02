#!/usr/bin/env python3
"""style-transfer · 规则化语气迁移（词表替换 + 句式调整，确定性）。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# 每个目标风格 = 一组 (正则, 替换, 人话)
STYLES: dict[str, list[tuple[re.Pattern[str], str, str]]] = {
    "colloquial": [
        (re.compile(r"因此"), "所以", "书面连接词→口语"),
        (re.compile(r"但是"), "但", "去公文转折"),
        (re.compile(r"然而"), "不过", "去公文转折"),
        (re.compile(r"非常"), "特别", "程度副词口语化"),
        (re.compile(r"我认为|笔者认为"), "我觉得", "第一人称"),
        (re.compile(r"无法"), "没办法", "去书面否定"),
        (re.compile(r"由于"), "因为", "去书面因果"),
        (re.compile(r"能够|可以做到"), "能", "去书面能力表述"),
        (re.compile(r"许多"), "很多", "去书面量词"),
        (re.compile(r"目前"), "现在", "去公文时间词"),
        (re.compile(r"之后"), "后来", "去公文时间词"),
        (re.compile(r"建议您"), "最好", "去公文建议"),
        (re.compile(r"该(产品|方案|功能|方法)"), r"这个\1", "去公文指代"),
        (re.compile(r"进行(了)?(优化|调整|分析|说明)"), r"\2一下", "去「进行+N」"),
    ],
    "funny": [
        (re.compile(r"非常"), "真的巨", "夸张化"),
        (re.compile(r"十分"), "相当", "夸张化"),
        (re.compile(r"值得注意的是"), "你猜怎么着", "去提示套话"),
        (re.compile(r"我个人认为"), "我赌五毛", "网感句式"),
        (re.compile(r"因此"), "所以咯", "口语连接"),
        (re.compile(r"具有(.{1,6})的能力"), r"能\1，一整个爱住", "去名词化"),
        (re.compile(r"用户"), "咱们", "人称改造"),
        (re.compile(r"进行(了)?(优化|调整)"), r"狠狠\2", "夸张化"),
        (re.compile(r"需要注意的是"), "血泪提醒", "网感句式"),
        (re.compile(r"提升"), "卷", "网感词"),
        (re.compile(r"降低"), "打下来", "网感词"),
        (re.compile(r"。$"), "，懂的都懂。", "口播收尾"),
    ],
    "pro": [
        (re.compile(r"很多|好多"), "多数", "量词专业化"),
        (re.compile(r"挺|特别|超级"), "较为", "程度副词专业化"),
        (re.compile(r"爆火|火了"), "获得高曝光", "去情绪词"),
        (re.compile(r"真的"), "在实测条件下", "加限定条件"),
        (re.compile(r"我觉得"), "综合上述因素可判断", "显式化判断依据"),
        (re.compile(r"便宜|贵"), "成本/收益比", "换量化口径"),
    ],
    "warm": [
        (re.compile(r"^"), "先说结论：", "共情前缀"),
        (re.compile(r"用户"), "你", "人称改造"),
        (re.compile(r"需要注意"), "先提醒你一句", "亲和化"),
        (re.compile(r"建议"), "我更想劝你", "亲和化"),
        (re.compile(r"。$"), "，希望帮到你～", "亲和收尾"),
    ],
    "serious": [
        (re.compile(r"真的巨|很牛|绝了|救命|血泪|懂的都懂|一整个"), "", "去网感"),
        (re.compile(r"哈哈|233|笑死"), "", "去口语梗"),
        (re.compile(r"。$"), "。", "收回口播"),
        (re.compile(r"咱们|你猜"), "读者", "去网络称谓"),
        (re.compile(r"挺"), "较为", "去口语程度词"),
        (re.compile(r"特别"), "尤其", "程度副词正式化"),
    ],
}

COST_NOTE = {
    "colloquial": "口语化后正式措辞变弱，引用官方口径时慎用",
    "funny": "夸张表达会降低信息密度，专业场景请勿使用",
    "pro": "术语化后门槛变高，新手读者可能读不懂",
    "warm": "亲和语气会稀释结论的锋利度",
    "serious": "去梗后传播力下降",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="style-transfer")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--out", default=os.environ.get("ATELIER_OUT", "."))
    ap.add_argument("--project", default=os.environ.get("ATELIER_PROJECT", "default"))
    return ap.parse_args(argv)


def emit(payload: dict) -> None:
    sys.stdout.write("ATELIER_RESULT " + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def apply_style(text: str, style: str) -> tuple[str, list[dict]]:
    out = text
    detail: list[dict] = []
    for pat, rep, label in STYLES[style]:
        hit = pat.search(out)
        if hit:
            n = len(pat.findall(out))
            detail.append({"rule": label, "count": n, "sample": hit.group(0)[:20]})
            out = pat.sub(rep, out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip(), detail


def slugify(text: str) -> str:
    s = "".join(c.lower() if c.isascii() and c.isalnum() else "-" for c in text[:20]).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s or "text"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        params = json.loads(args.params or "{}")
    except json.JSONDecodeError as e:
        print(f"style-transfer: --params 不是合法 JSON：{e}", file=sys.stderr)
        return 2
    text = str(params.get("text") or "").strip()
    if len(text) < 30:
        print(f"style-transfer: 原文只有 {len(text)} 字（需 ≥30），不迁移", file=sys.stderr)
        return 2
    to_style = str(params.get("to_style") or "colloquial")
    if to_style not in STYLES:
        print(f"style-transfer: to_style 非法 {to_style!r}，可选 {sorted(STYLES)}", file=sys.stderr)
        return 2
    from_style = str(params.get("from_style") or "serious")
    platform = str(params.get("platform") or "xhs")

    result, detail = apply_style(text, to_style)
    ratio = abs(len(result) - len(text)) / max(1, len(text))
    warn = ""
    if ratio > 0.2:
        warn = f"字数变化 {ratio:.0%}（{len(text)} → {len(result)}），语气改动可能已改变信息密度，请人工确认"
        print(f"style-transfer: WARNING {warn}", file=sys.stderr)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{slugify(text)}-{to_style}.md"
    rows = "\n".join(f"- {d['rule']} ×{d['count']}（例：{d['sample']}）" for d in detail) or "- （无命中）"
    path.write_text(
        f"# 风格迁移 · {from_style} → {to_style} · 平台 {platform}\n\n"
        f"## 改后\n\n{result}\n\n## 替换明细\n\n{rows}\n\n"
        f"## 风格差异提示\n\n- {COST_NOTE[to_style]}\n"
        + (f"- {warn}\n" if warn else "")
        + "\n> 规则迁移，不重新创作：规则改不出的语气请人工润色。\n",
        encoding="utf-8",
    )
    print(f"style-transfer: → {to_style}，命中 {len(detail)} 条规则")
    print(f"style-transfer: 已写入 {path.name}")
    emit(
        {
            "artifacts": [{"path": str(path), "kind": "markdown", "name": path.name}],
            "summary": f"{from_style} → {to_style}，命中 {len(detail)} 条规则",
            "to_style": to_style,
            "detail": detail,
            "warning": warn,
            "result_markdown": result,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
