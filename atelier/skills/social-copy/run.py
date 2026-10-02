#!/usr/bin/env python3
"""social-copy · 五平台文案骨架生成器（确定性结构，填充由 agent 承接）。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PLATFORMS = {
    "xhs": {"name": "小红书", "title": 20, "body": 1000, "tags": 8, "style": "短句 + emoji 分隔"},
    "weibo": {"name": "微博", "title": 0, "body": 140, "tags": 3, "style": "单段 + #话题#"},
    "zhihu": {"name": "知乎", "title": 50, "body": 20000, "tags": 5, "style": "结论前置 + 给依据"},
    "gzh": {"name": "公众号", "title": 30, "body": 20000, "tags": 0, "style": "导语 + 小标题"},
    "bili": {"name": "B站", "title": 80, "body": 2000, "tags": 10, "style": "标题带反差 + 简介 3 行"},
}
TONES = {
    "friend": {"emoji": "✨", "cta": "有问题评论区喊我"},
    "pro": {"emoji": "📌", "cta": "需要模板私信"},
    "sharp": {"emoji": "⚡️", "cta": "不同意就来杠"},
}
STOP = set("的了是我你他她它们在和与及就都也而但却很更不没有这那个一个可以我们你们如何什么怎么为什么")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="social-copy")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--out", default=os.environ.get("ATELIER_OUT", "."))
    ap.add_argument("--project", default=os.environ.get("ATELIER_PROJECT", "default"))
    return ap.parse_args(argv)


def emit(payload: dict) -> None:
    sys.stdout.write("ATELIER_RESULT " + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def keywords(text: str, n: int) -> list[str]:
    """抽标签：按标点/空白切出「语义完整的连续片段」，**不按固定字数切碎中文**。

    早期版本用 ``[一-鿿]{2,6}`` 定长切分，会切出「#件事#」「#连发#」这种无意义标签。
    """
    freq: dict[str, int] = {}
    for seg in re.findall(r"[A-Za-z][A-Za-z0-9]{1,15}|[一-鿿]+", text):
        if len(seg) < 2 or len(seg) > 8:
            continue
        if seg.lower() in STOP or seg in STOP:
            continue
        if seg[0] in STOP or seg[-1] in STOP:
            continue
        freq[seg] = freq.get(seg, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    return [k for k, _ in ranked[:n]]


def count(text: str) -> int:
    """字数口径：去空白计字符（与门禁一致）。"""
    return len(re.sub(r"\s", "", text))


def clip(text: str, limit: int) -> str:
    """超长才截断；**保留换行**。

    早期版本对全文做 ``re.sub(r"\\s", "")``，把小红书正文的分段结构压成一行，
    排版直接报废。截断只在真的超限时发生。
    """
    if count(text) <= limit:
        return text
    out, seen = [], 0
    for ch in text:
        if ch.isspace():
            out.append(ch)
            continue
        seen += 1
        if seen > limit - 1:
            out.append("…")
            break
        out.append(ch)
    return "".join(out)


def title_candidates(topic: str, points: list[str]) -> list[str]:
    base = clip(topic, 20)
    cands = [base]
    if points:
        cands.append(clip(f"{points[0]}，我用{base}", 20))
    cands.append(clip(f"别再乱试了：{base}", 20))
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out[:3]


def build(topic: str, platform: str, tone: dict, points: list[str]) -> dict:
    p = PLATFORMS[platform]
    t = tone["emoji"]
    # 标签优先用用户给的 keypoints（已是干净短语），再补 topic 抽出来的
    from_points = [x for x in points if 2 <= len(x) <= 8]
    tags = list(dict.fromkeys(from_points + keywords(topic, p["tags"] if p["tags"] else 3)))
    tags = tags[: p["tags"] or len(tags)]
    if not tags:
        tags = ["日常"]  # 兜底占位：宁可给一个通用标签，也别让标签区空着
    if platform == "weibo":
        body = f"{clip(topic, 110)} {t}"
        body += " " + " ".join(f"#{x}#" for x in tags[:3])
    elif platform == "xhs":
        seg = [f"{i + 1}. {x}" for i, x in enumerate(points)] or [f"1. {clip(topic, 60)}"]
        body = f"{t} {clip(topic, 40)}\n\n" + "\n".join(seg) + f"\n\n{t} {tone['cta']}\n\n" + " ".join(
            f"#{x}#" for x in tags
        )
    elif platform == "zhihu":
        body = f"先给结论：{clip(topic, 80)}。\n\n依据：\n" + "\n".join(
            f"- {x}" for x in (points or ["（待补依据）"])
        )
    elif platform == "gzh":
        body = f"{t} 导语：{clip(topic, 80)}\n\n" + "\n\n".join(
            f"## {x}\n（正文待 agent 填充）" for x in (points or ["正文"])
        ) + f"\n\n{t} {tone['cta']}"
    else:  # bili
        body = f"{clip(topic, 70)}\n" + "\n".join(f"- {x}" for x in (points or ["（待补）"]))
        body += f"\n{t} {tone['cta']}"
    body = clip(body, p["body"]) if p["body"] < 20000 else body
    n = count(body)
    return {
        "platform": platform,
        "platform_name": p["name"],
        "titles": title_candidates(topic, points),
        "body": body,
        "tags": [f"#{x}#" for x in tags] if platform in ("xhs", "weibo", "bili") else tags,
        "char_count": n,
        "limit": p["body"],
        "over_limit": n > p["body"],
        "style_note": p["style"],
    }


def slugify(text: str) -> str:
    s = "".join(c.lower() if c.isascii() and c.isalnum() else "-" for c in text[:18]).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s or "copy"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        params = json.loads(args.params or "{}")
    except json.JSONDecodeError as e:
        print(f"social-copy: --params 不是合法 JSON：{e}", file=sys.stderr)
        return 2
    topic = str(params.get("topic") or "").strip()
    if len(topic) < 10:
        print(f"social-copy: topic 只有 {len(topic)} 字（需 ≥10），不猜内容，请回问用户", file=sys.stderr)
        return 2
    tone_name = str(params.get("tone") or "friend")
    if tone_name not in TONES:
        print(f"social-copy: tone 非法 {tone_name!r}，可选 {sorted(TONES)}", file=sys.stderr)
        return 2
    raw_points = str(params.get("keypoints") or "")
    points = [x.strip() for x in re.split(r"[,，;；\n]", raw_points) if x.strip()]
    target = str(params.get("platform") or "all")
    if target != "all" and target not in PLATFORMS:
        print(f"social-copy: platform 非法 {target!r}，可选 {sorted(PLATFORMS)} 或 all", file=sys.stderr)
        return 2
    targets = list(PLATFORMS) if target == "all" else [target]
    tone = TONES[tone_name]

    results = [build(topic, p, tone, points) for p in targets]
    over = [r["platform"] for r in results if r["over_limit"]]
    if over:
        print(f"social-copy: {over} 正文超限，需调用 crop 技能裁剪，不许硬塞", file=sys.stderr)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    arts = []
    if target == "all":
        path = out / f"{slugify(topic)}-all.md"
        parts = [f"# 通用社媒文案 · {topic}\n"]
        for r in results:
            parts.append(
                f"## {r['platform_name']}（{r['platform']}）\n\n"
                f"**标题候选**：{' / '.join(r['titles'])}\n\n{r['body']}\n\n"
                f"- 标签：{' '.join(r['tags']) or '—'}\n"
                f"- 字数：{r['char_count']}/{r['limit']} {'⚠️超限' if r['over_limit'] else 'OK'}\n"
                f"- 体裁：{r['style_note']}\n"
            )
        path.write_text("\n".join(parts), encoding="utf-8")
        arts.append({"path": str(path), "kind": "markdown", "name": path.name})
    else:
        for r in results:
            path = out / f"{slugify(topic)}-{r['platform']}.md"
            path.write_text(
                f"# {r['platform_name']}文案\n\n**标题候选**：{' / '.join(r['titles'])}\n\n{r['body']}\n\n"
                f"- 标签：{' '.join(r['tags']) or '—'}\n- 字数：{r['char_count']}/{r['limit']}\n",
                encoding="utf-8",
            )
            arts.append({"path": str(path), "kind": "markdown", "name": path.name})

    print(f"social-copy: 生成 {len(results)} 个平台版本，{len(arts)} 个文件")
    for r in results:
        print(f"social-copy:   {r['platform_name']:4s} {r['char_count']}/{r['limit']} 字")
    emit(
        {
            "artifacts": arts,
            "summary": f"{len(results)} 平台版本" + (f"，{over} 超限" if over else ""),
            "variants": results,
            "over_limit": over,
            "result_markdown": results[0]["body"] if results else "",
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
