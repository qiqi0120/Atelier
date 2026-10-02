#!/usr/bin/env python3
"""viral-decode · 爆款拆解「原帖事实」抽取（确定性部分；观点段由 agent 承接）。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SECTIONS = [
    "原帖事实",
    "爆点定位",
    "结构拆解",
    "情绪曲线",
    "可复用公式",
    "我的改写建议",
]
HOOK = re.compile(r"(不是.{0,10}而是|别再|千万别|其实|真相|为什么|居然|竟然|后悔|踩坑|翻车|第一次|第[一二三四五六七八九十]个|\d+个)")
NUM = re.compile(r"\d")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="viral-decode")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--out", default=os.environ.get("ATELIER_OUT", "."))
    ap.add_argument("--project", default=os.environ.get("ATELIER_PROJECT", "default"))
    return ap.parse_args(argv)


def emit(payload: dict) -> None:
    sys.stdout.write("ATELIER_RESULT " + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def split_sentences(text: str) -> list[str]:
    flat = re.sub(r"\s*\n\s*", "，", text.strip())
    return [s.strip() for s in re.split(r"(?<=[。！？!?；;])", flat) if s.strip()]


def parse_metrics(raw: str) -> list[tuple[str, str]]:
    """抽「标签 + 数值」对。

    早期版本先按空白切分，``赞 3.2w`` 会被切成 ``赞`` 和 ``3.2w``，
    前者不匹配丢数据、后者被误当成「标签 3 / 值 .2w」。改为整体 findall。
    """
    return re.findall(r"([一-鿿A-Za-z]{1,4})\s*[:：]?\s*([\d.]+\s*[wWkK万千]?)", raw.strip())


def slugify(text: str) -> str:
    s = "".join(c.lower() if c.isascii() and c.isalnum() else "-" for c in text[:20]).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s or "viral"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        params = json.loads(args.params or "{}")
    except json.JSONDecodeError as e:
        print(f"viral-decode: --params 不是合法 JSON：{e}", file=sys.stderr)
        return 2
    text = str(params.get("text") or "").strip()
    if len(text) < 40:
        print(f"viral-decode: 原文只有 {len(text)} 字（需 ≥40），拆不动", file=sys.stderr)
        return 2
    platform = str(params.get("platform") or "xhs")
    goal = str(params.get("goal") or "涨粉")
    metrics_raw = str(params.get("metrics") or "")
    metrics = parse_metrics(metrics_raw)
    sents = split_sentences(text)
    facts = [f"字数（不含空白）：{len(re.sub(r'[[:space:]]', '', text))}"]
    facts.append(f"句数：{len(sents)}")
    facts.append(f"首句：{sents[0][:40] if sents else '—'}")
    if NUM.search(text):
        nums = sorted(set(NUM.findall(text)))
        facts.append(f"含数字：{'、'.join(nums[:6])}")
    tags = re.findall(r"#([^#\s]{1,12})#", text)
    if tags:
        facts.append(f"话题：{'、'.join('#' + t + '#' for t in tags[:5])}")
    if metrics:
        facts.append("数据表现：" + "、".join(f"{k} {v}" for k, v in metrics))
    else:
        facts.append("数据表现：未提供数据，不做效果归因")

    hits = [(i, s) for i, s in enumerate(sents) if HOOK.search(s)]
    if hits:
        idx, s = hits[0]
        hook = f"第 {idx + 1} 句「{s[:48]}」命中钩子词"
    else:
        first = min(sents, key=len) if sents else ""
        hook = f"未命中显性钩子词；最短句「{first[:40]}」可能是留白式开头（如实记录，不编造爆点）"

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{slugify(text)}.md"
    fact_lines = "\n".join(f"- {f}" for f in facts)
    doc = (
        f"# 爆款拆解 · 平台 {platform} · 目标 {goal}\n\n"
        f"## 1. {SECTIONS[0]}\n\n{fact_lines}\n\n"
        f"## 2. {SECTIONS[1]}\n\n- {hook}\n\n"
        f"## 3. {SECTIONS[2]}\n\n（待 agent 依据第 1 段事实填写，禁止编造原帖没有的内容）\n\n"
        f"## 4. {SECTIONS[3]}\n\n（待 agent 填写）\n\n"
        f"## 5. {SECTIONS[4]}\n\n（待 agent 填写）\n\n"
        f"## 6. {SECTIONS[5]}\n\n（待 agent 填写，须结合目标：{goal}）\n\n"
        "> 只拆结构，不抄内容。第 1–2 段由脚本确定性产出，第 3–6 段由 agent 撰写。\n"
    )
    path.write_text(doc, encoding="utf-8")
    print(f"viral-decode: 事实抽取完成（{len(facts)} 条事实，{len(sents)} 句）")
    print(f"viral-decode: 已写入 {path.name}，6 段骨架待 agent 补全 3–6 段")
    emit(
        {
            "artifacts": [{"path": str(path), "kind": "markdown", "name": path.name}],
            "summary": f"抽取 {len(facts)} 条事实，钩子：{hook[:30]}",
            "facts": facts,
            "hook": hook,
            "sections": SECTIONS,
            "result_markdown": f"## 1. {SECTIONS[0]}\n\n{fact_lines}",
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
