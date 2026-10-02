#!/usr/bin/env python3
"""de-ai · 去 AI 感确定性改写器（规则实现，可复现，不联网）。"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from itertools import pairwise
from pathlib import Path

# (正则, 人话说明) —— 命中即整段删除或替换
FILLERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"众所周知[，,、]?"), "无信息量开场"),
    (re.compile(r"在这个快节奏的时代[，,]?"), "时代背景套话"),
    (re.compile(r"在当今社会[，,]?"), "时代背景套话"),
    (re.compile(r"随着[^，。；]{0,14}的(发展|进步|变迁)[，,]?"), "宏大背景套话"),
    (re.compile(r"不可否认(的是)?"), "强调套话"),
    (re.compile(r"值得一提的是[，,]?"), "提示套话"),
    (re.compile(r"值得注意的是[，,]?"), "提示套话"),
    (re.compile(r"总的来说[，,]?"), "总结套话"),
    (re.compile(r"总而言之[，,]?"), "总结套话"),
    (re.compile(r"综上所述[，,]?"), "总结套话"),
    (re.compile(r"让我们(一起|来)[^，。]{0,10}"), "号召套话"),
    (re.compile(r"不难(发现|看出)"), "伪客观句式"),
    (re.compile(r"不仅仅是[^，。]{1,12}[，,]?更(是|是)"), "「不仅…更是」排比"),
    (re.compile(r"(其实|说白了|讲真)[，,]?"), "口水前缀"),
    (re.compile(r"我个人认为[，,]?"), "主观前缀"),
    (re.compile(r"在(这个|当下|如今)的[^，。]{0,10}里[，,]?"), "空场景"),
    (re.compile(r"无疑(地)?"), "绝对化副词"),
    (re.compile(r"赋能|抓手|闭环|颗粒度|对齐|心智|势能|打法|护城河"), "互联网黑话"),
]

# 主动语态修正
PASSIVES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"被([^，。；]{1,8})所([一-鿿]{1,4})"), "被动句式"),
    (re.compile(r"进行了([一-鿿]{2,6})"), "「进行了」公文腔"),
    (re.compile(r"有一个([一-鿿]{1,8})[，,](?:叫做|叫)"), "绕口句式"),
    (re.compile(r"实现了([一-鿿]{2,6})"), "公文腔"),
    (re.compile(r"对于([^，。；]{1,10})来说"), "绕口句式"),
]

CHAIN = re.compile(r"(首先|其次|然后|再次|最后|此外|另外)[，,、]?")
TRUST = re.compile(r"(\d|[一二三四五六七八九十百千万]*(年|月|日|块|元|次|天|小时|倍|%)|我|我们|亲测|实测|试了|用了|踩坑)")
SPOKEN = re.compile(r"(吧|啊|呢|真的|其实|反正|你别说|离谱|坑|就这|个人感觉|[!?！？])")
CONCRETE = re.compile(r"\d")

SPLIT = re.compile(r"(?<=[。！？!?；;])")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="de-ai rewriter")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--out", default=os.environ.get("ATELIER_OUT", "."))
    ap.add_argument("--project", default=os.environ.get("ATELIER_PROJECT", "default"))
    return ap.parse_args(argv)


def emit(payload: dict) -> None:
    sys.stdout.write("ATELIER_RESULT " + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def split_sentences(text: str) -> list[str]:
    out = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        out.extend(s.strip() for s in SPLIT.split(para) if s.strip())
    return out


def sentences_len(sents: list[str]) -> list[int]:
    return [len(s.rstrip("。！？!?；;")) for s in sents]


def alternate(sents: list[str], strength: str) -> tuple[list[str], list[str]]:
    """长短句交替：连续三句长度极差过小则拆/并。"""
    changes: list[str] = []
    if len(sents) < 3:
        return sents, changes
    need = 5 if strength == "light" else (6 if strength == "medium" else 8)
    i = 0
    while i <= len(sents) - 3:
        trio = sents[i : i + 3]
        lens = sentences_len(trio)
        if max(lens) - min(lens) < need and max(lens) >= 14:
            long_i = lens.index(max(lens))
            s = trio[long_i]
            cut = len(s) // 2
            for k in range(cut, min(len(s), cut + 12)):
                if s[k] in "，,、":
                    cut = k + 1
                    break
            head, tail = s[:cut], s[cut:]
            if tail.strip():
                trio[long_i : long_i + 1] = [head, tail]
                sents[i : i + 3] = trio
                changes.append(f"第 {i + 1} 句过长，拆成长短两句以打破等长节奏")
                i += 3
                continue
        i += 1
    return sents, changes


def desugar(text: str, strength: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    out = text
    for pat, label in FILLERS:
        new, n = pat.subn("", out)
        if n:
            changes.append(f"删除填充语「{pat.pattern[:14]}」（{label}）×{n}")
            out = new
    for pat, label in PASSIVES:
        new, n = pat.subn(lambda m: m.group(1) + m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(0), out)
        if n:
            changes.append(f"改主动语态（{label}）×{n}")
            out = new
    n_chain = len(CHAIN.findall(out))
    if n_chain >= 2:
        out = CHAIN.sub("", out)
        changes.append(f"拆掉「首先/其次/最后」并列骨架 ×{n_chain}，打散模板结构")
    sents = split_sentences(out)
    sents, alt = alternate(sents, strength)
    changes.extend(alt)
    if not sents:
        return out, changes
    # 段间等长检测：段落字数极差 < 15% 则重排（长段往后放）
    paras = [p for p in out.split("\n") if p.strip()]
    if len(paras) >= 3:
        lens = [len(p) for p in paras]
        if max(lens) and (max(lens) - min(lens)) / max(lens) < 0.15:
            paras.sort(key=len, reverse=True)
            changes.append("三段字数过于接近，重排段序让信息密度有起伏")
            out = "\n".join(paras)
    return out, changes


def score(text: str) -> dict[str, int]:
    sents = split_sentences(text)
    lens = sentences_len(sents) or [0]
    total = len(text)
    avg = statistics.fmean(lens) if lens else 0
    std = statistics.pstdev(lens) if len(lens) > 1 else 0.0

    opener_filler = sum(1 for pat, _ in FILLERS if sents and pat.match(sents[0]))
    direct = 100 - 45 * opener_filler - (12 if CHAIN.match(sents[0] if sents else "") else 0)
    direct += 8 if sents and lens[0] <= 18 else 0
    direct = max(0, min(100, int(direct)))

    rhythm = int(min(100, (std / max(1.0, avg * 0.55)) * 100)) if avg else 0
    altern = sum(1 for a, b in pairwise(lens) if abs(a - b) >= 6)
    rhythm = int(min(100, rhythm * 0.7 + (altern / max(1, len(lens) - 1)) * 100 * 0.3))
    rhythm = max(0, min(100, rhythm))

    trust_hits = len(TRUST.findall(text))
    trust = int(min(100, 30 + trust_hits * 9))

    spoken = len(SPOKEN.findall(text))
    residue = sum(len(pat.findall(text)) for pat, _ in FILLERS)
    human = max(0, min(100, int(45 + spoken * 8 - residue * 25)))

    density = total / max(1, len(sents)) if sents else total
    concise = int(min(100, 100 - max(0, density - 22) * 3 + min(20, len(SPOKEN.findall(text)))))
    concise = max(0, min(100, concise))

    return {
        "直接性": direct,
        "节奏": max(0, min(100, rhythm)),
        "信任度": trust,
        "活人感": human,
        "精炼度": concise,
    }


def slugify(text: str) -> str:
    s = "".join(c.lower() if c.isascii() and c.isalnum() else "-" for c in text[:24]).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s or "draft"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        params = json.loads(args.params or "{}")
    except json.JSONDecodeError as e:
        print(f"de-ai: --params 不是合法 JSON：{e}", file=sys.stderr)
        return 2
    text = str(params.get("text") or "").strip()
    if len(text) < 30:
        print(f"de-ai: 原文只有 {len(text)} 字（需 ≥30），不构成改写；如需重写请用 social-copy", file=sys.stderr)
        return 2
    strength = str(params.get("strength") or "medium")
    if strength not in ("light", "medium", "strong"):
        print(f"de-ai: strength 非法 {strength!r}，可选 light/medium/strong", file=sys.stderr)
        return 2
    platform = str(params.get("platform") or "xhs")
    keep_facts = str(params.get("keep_facts", "true")).lower() not in ("false", "0", "no")

    before_score = score(text)
    new_text, changes = desugar(text, strength)

    if keep_facts:
        lost = sorted(set(CONCRETE.findall(text)) - set(CONCRETE.findall(new_text)))
        if lost:
            print(
                f"de-ai: 改写丢失了数字事实 {lost}，keep_facts=true 下判定失败，已回滚为原文",
                file=sys.stderr,
            )
            new_text = text
            changes.append(f"⚠️ 命中 keep_facts 保护：丢失数字 {lost}，已回滚")

    after_score = score(new_text)
    delta = {k: after_score[k] - before_score[k] for k in before_score}
    total_before = sum(before_score.values()) // 5
    total_after = sum(after_score.values()) // 5
    residual = sum(len(pat.findall(new_text)) for pat, _ in FILLERS)
    if residual:
        print(f"de-ai: 改后仍残留 {residual} 处填充语，强度已到上限", file=sys.stderr)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{slugify(text)}-deai.md"
    rows = "\n".join(
        f"| {k} | {before_score[k]} | {after_score[k]} | {delta[k]:+d} |" for k in before_score
    )
    chg = "\n".join(f"- {c}" for c in changes) or "- （未命中任何规则，原文已较自然）"
    path.write_text(
        f"# 去 AI 感改写 · 力度 {strength} · 平台 {platform}\n\n"
        f"## 改前\n\n{text}\n\n## 改后\n\n{new_text}\n\n"
        f"## 五维对比\n\n| 维度 | 改前 | 改后 | 变化 |\n|---|---|---|---|\n{rows}\n\n"
        f"综合：{total_before} → {total_after}（{total_after - total_before:+d}）\n\n"
        f"## 改了哪些\n\n{chg}\n",
        encoding="utf-8",
    )
    print(f"de-ai: 综合分 {total_before} → {total_after}，规则命中 {len(changes)} 条")
    print(f"de-ai: 已写入 {path.name}")
    emit(
        {
            "artifacts": [{"path": str(path), "kind": "markdown", "name": path.name}],
            "summary": f"五维综合 {total_before} → {total_after}",
            "score_before": before_score,
            "score_after": after_score,
            "total_before": total_before,
            "total_after": total_after,
            "changes": changes,
            "residual_fillers": residual,
            "result_markdown": f"## 改后\n\n{new_text}\n\n## 五维对比\n\n{rows}",
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
