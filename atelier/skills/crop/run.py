#!/usr/bin/env python3
"""crop · 字数裁剪 / 抽取式摘要 / 金句提取（确定性）。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

LIMITS = {"xhs": 1000, "dy": 55, "gzh": 20000, "zhihu": 20000, "bili": 2000, "weibo": 140}
MODES = ("crop", "summary", "golden")
SPLIT = re.compile(r"(?<=[。！？!?；;])")
STOP = set("的了是我你他她它们在和与及就都也而但却很更不没有啊吧呢着过对从把被让使将")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="crop / summary / golden sentences")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--out", default=os.environ.get("ATELIER_OUT", "."))
    ap.add_argument("--project", default=os.environ.get("ATELIER_PROJECT", "default"))
    return ap.parse_args(argv)


def emit(payload: dict) -> None:
    sys.stdout.write("ATELIER_RESULT " + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def count(text: str) -> int:
    """字数口径：与门禁一致，去空白计字符。"""
    return len(re.sub(r"\s", "", text))


def sentences(text: str) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if para:
            out.extend(s.strip() for s in SPLIT.split(para) if s.strip())
    return out


def density(s: str) -> float:
    chars = [c for c in s if c not in STOP]
    digits = len(re.findall(r"\d", s))
    if not s:
        return 0.0
    return (len(chars) + digits * 3) / (len(s) ** 0.5)


def golden_score(s: str) -> float:
    n = count(s)
    if n < 6 or n > 40:
        return 0.0
    score = 10.0
    if re.search(r"\d", s):
        score += 6
    if re.search(r"(不是.+而是|越.+越|与其.+不如|只要.+就|第一|最后|真正|本质)", s):
        score += 5
    if re.search(r"[!?！？]", s):
        score += 2
    if re.search(r"(你|我|咱们)", s):
        score += 2
    if re.search(r"(其实|反正|就这|真的|别再|千万别)", s):
        score += 3
    if re.search(r"(总而言之|综上所述|值得注意的是|众所周知)", s):
        score -= 8
    return score - abs(n - 20) * 0.15


def do_crop(text: str, limit: int) -> tuple[str, int, bool]:
    if count(text) <= limit:
        return text, count(text), False
    kept: list[str] = []
    total = 0
    for s in sentences(text):
        c = count(s)
        if total + c > limit:
            break
        kept.append(s)
        total += c
    return ("".join(kept).strip(), total, True)


def do_top(text: str, limit: int, scorer) -> tuple[str, list[str]]:
    sents = sentences(text)
    ranked = sorted(enumerate(sents), key=lambda kv: scorer(kv[1]), reverse=True)
    picked: list[tuple[int, str]] = []
    total = 0
    for idx, s in ranked:
        c = count(s)
        if total + c > limit:
            continue
        picked.append((idx, s))
        total += c
    picked.sort(key=lambda kv: kv[0])
    return "".join(s for _, s in picked).strip(), [s for _, s in picked]


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
        print(f"crop: --params 不是合法 JSON：{e}", file=sys.stderr)
        return 2
    text = str(params.get("text") or "").strip()
    if not text:
        print("crop: 缺少 text", file=sys.stderr)
        return 2
    mode = str(params.get("mode") or "crop")
    if mode not in MODES:
        print(f"crop: mode 非法 {mode!r}，可选 {list(MODES)}", file=sys.stderr)
        return 2
    platform = str(params.get("platform") or "xhs")
    try:
        limit = int(params.get("limit") or LIMITS.get(platform, 1000))
    except (TypeError, ValueError):
        print(f"crop: limit 非法 {params.get('limit')!r}", file=sys.stderr)
        return 2
    if limit < 10:
        print(f"crop: limit={limit} 过小，至少 10", file=sys.stderr)
        return 2

    trimmed = False
    if mode == "crop":
        result, _n, trimmed = do_crop(text, limit)
        picked = [result]
    elif mode == "summary":
        result, picked = do_top(text, limit, density)
    else:
        result, picked = do_top(text, max(limit, 120), golden_score)

    before, after = count(text), count(result)
    dropped = text if not trimmed and mode == "crop" else ""
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{slugify(text)}-{mode}.md"
    if mode == "golden":
        body = "\n".join(f"> {s}" for s in picked) or result
    else:
        body = result
    extra = "" if trimmed or mode != "crop" else "\n\n> 原文未超限，原样返回。\n"
    path.write_text(
        f"# {mode} · 平台 {platform} · limit {limit}\n\n## 结果\n\n{body}\n{extra}\n"
        f"## 字数\n\n{before} 字 → {after} 字（limit {limit}，{'已裁剪' if trimmed else '未裁剪'}）\n\n"
        f"## 裁掉的部分\n\n{dropped or '（无）'}\n",
        encoding="utf-8",
    )
    print(f"crop: {mode} 完成，{before} → {after} 字（limit {limit}）")
    if mode == "golden":
        print(f"crop: 提取 {len(picked)} 句候选金句")
    print(f"crop: 已写入 {path.name}")
    label = f"{mode}：提取 {len(picked)} 句" if mode == "golden" else f"{mode}：{before} → {after} 字（limit {limit}）"
    emit(
        {
            "artifacts": [{"path": str(path), "kind": "markdown", "name": path.name}],
            "summary": label,
            "mode": mode,
            "char_before": before,
            "char_after": after,
            "limit": limit,
            "trimmed": trimmed,
            "sentences": picked,
            "result_markdown": body,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
