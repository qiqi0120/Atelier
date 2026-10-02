#!/usr/bin/env python3
"""precheck · 发布前预检（确定性门禁，BLOCK/WARN 分级，secret 扫描 fail-closed）。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

LIMITS = {"xhs": 1000, "dy": 55, "gzh": 20000}
PLATFORM_NAMES = {"xhs": "小红书", "dy": "抖音", "gzh": "微信公众号"}
EXTREME = [
    "最好", "最佳", "第一", "国家级", "顶级", "唯一", "全网最", "史上最", "永久", "根治", "绝对",
    "百分百", "100%", "无副作用", "包治", "神药", "立刻见效",
]
FORBIDDEN = [
    "发票", "代开发票", "博彩", "彩票", "处方药", "违禁", "走私", "代购正品", "包过", "内部渠道",
]
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{12,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S{8,}"),
    re.compile(r"1[3-9]\d{9}"),
]
FILLER = re.compile(
    r"众所周知|在这个快节奏的时代|值得注意的是|总而言之|综上所述|让我们一起|在当今社会|不得不说"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="precheck")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--out", default=os.environ.get("ATELIER_OUT", "."))
    ap.add_argument("--project", default=os.environ.get("ATELIER_PROJECT", "default"))
    return ap.parse_args(argv)


def emit(payload: dict) -> None:
    sys.stdout.write("ATELIER_RESULT " + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def item(gate: str, label: str, severity: str, passed: bool, actual, limit, message: str, hint: str = "") -> dict:
    return {
        "gate": gate,
        "label": label,
        "severity": severity,
        "passed": passed,
        "actual": actual,
        "limit": limit,
        "message": message,
        "fix_hint": hint or None,
    }


def hits(text: str, words: list[str]) -> list[str]:
    return [w for w in words if w in text]


def run_checks(title: str, body: str, platform: str, hashtags: list[str]) -> tuple[list[dict], bool]:
    text = f"{title}\n{body}"
    items: list[dict] = []
    items.append(
        item("title", "标题非空", "block", bool(title.strip()), len(title.strip()), 1,
             "标题已填" if title.strip() else "标题为空，不能发",
             "" if title.strip() else "先写一个 20 字内的标题")
    )
    limit = LIMITS.get(platform, 1000)
    n = len(re.sub(r"\s", "", body))
    items.append(
        item("wordcount", f"{PLATFORM_NAMES.get(platform, platform)}正文字数", "block", n <= limit, n, limit,
             f"{n} 字（上限 {limit}）" if n <= limit else f"超限 {n - limit} 字",
             "" if n <= limit else f"点「字数裁剪」技能压到 {limit} 字内")
    )
    ex = hits(text, EXTREME)
    items.append(
        item("compliance", "极限词 / 医疗功效", "block", not ex, ex or "无", "0",
             "未命中" if not ex else f"命中 {len(ex)} 个：{'、'.join(ex[:5])}",
             "" if not ex else "删除或换成可验证的具体描述")
    )
    fb = hits(text, FORBIDDEN)
    items.append(
        item("compliance", "违禁品词", "block", not fb, fb or "无", "0",
             "未命中" if not fb else f"命中：{'、'.join(fb)}", "" if not fb else "删除该表述")
    )
    try:
        sec = [m.group(0)[:24] for p in SECRET_PATTERNS for m in p.finditer(text)]
        scan_ok, scan_note = True, ""
    except Exception as e:  # noqa: BLE001 — fail-closed
        sec, scan_ok, scan_note = ["<扫描器异常>"], False, f"扫描器异常：{e}（按命中处理）"
        print(f"precheck: {scan_note}", file=sys.stderr)
    items.append(
        item("secret_scan", "密钥 / 敏感信息", "block", scan_ok and not sec, sec or "无", "0",
             "未发现" if scan_ok and not sec else f"发现疑似敏感信息 {sec[:3]}" + (" " + scan_note if scan_note else ""),
             "" if scan_ok and not sec else "从正文里删掉，换成占位符")
    )
    lo, hi = (5, 10) if platform == "xhs" else (0, 12)
    ok_tags = len(hashtags) == 0 or lo <= len(hashtags) <= hi
    items.append(
        item("hashtags", "话题标签数量", "warn", ok_tags, len(hashtags), f"{lo}-{hi}",
             "未使用话题" if not hashtags else f"{len(hashtags)} 个",
             "" if ok_tags else f"建议 {lo}–{hi} 个")
    )
    head = re.sub(r"\s", "", body)[:40]
    lead = bool(head) and (FILLER.search(head) is None)
    items.append(
        item("hook", "开头是否铺垫过长", "warn", lead, head[:16] or "空", "前 40 字给结论",
             "开头直接给结论" if lead else "开头是铺垫句，读者会划走", "把结论提到第一句")
    )
    fillers = FILLER.findall(text)
    items.append(
        item("ai_flavor", "AI 味（填充语）", "warn", not fillers, len(fillers), 0,
             "无填充语" if not fillers else f"命中 {len(fillers)} 处：{'、'.join(sorted(set(fillers))[:4])}",
             "" if not fillers else "跑一次「去 AI 感改写」")
    )
    blocked = any(i["severity"] == "block" and not i["passed"] for i in items)
    return items, not blocked


def slugify(text: str) -> str:
    s = "".join(c.lower() if c.isascii() and c.isalnum() else "-" for c in text[:20]).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s or "draft"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        params = json.loads(args.params or "{}")
    except json.JSONDecodeError as e:
        print(f"precheck: --params 不是合法 JSON：{e}", file=sys.stderr)
        return 2
    platform = str(params.get("platform") or "xhs")
    if platform not in LIMITS:
        print(f"precheck: platform 非法 {platform!r}，可选 {sorted(LIMITS)}", file=sys.stderr)
        return 2
    title = str(params.get("title") or "")
    body = str(params.get("body") or "")
    tags = [t.strip().lstrip("#") for t in re.split(r"[,，;；\s]+", str(params.get("hashtags") or "")) if t.strip()]

    items, passed = run_checks(title, body, platform, tags)
    blockers = [i for i in items if not i["passed"] and i["severity"] == "block"]
    warns = [i for i in items if not i["passed"] and i["severity"] == "warn"]
    rows = "\n".join(
        f"| {i['label']} | {i['severity'].upper()} | {'✅' if i['passed'] else '❌'} | {i['message']} | "
        f"{i['fix_hint'] if not i['passed'] else ''} |"
        for i in items
    )
    fixes = "\n".join(f"- **{i['label']}**：{i['fix_hint']}" for i in blockers + warns) or "- 无需修改"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{slugify(title or body)}-precheck.md"
    path.write_text(
        f"# 发布前预检 · {PLATFORM_NAMES[platform]}\n\n"
        f"## 结论\n\n{'✅ 可以发' if passed else '❌ 不可发布'}\n\n"
        f"BLOCK 未通过 {len(blockers)} 项，WARN {len(warns)} 项。\n\n"
        f"## 逐项结果\n\n| 项 | 分级 | 结果 | 说明 | 修法 |\n|---|---|---|---|---|\n{rows}\n\n"
        f"## 修法\n\n{fixes}\n\n> 预检不发布。实际发布走发布中心。\n",
        encoding="utf-8",
    )
    print(f"precheck: {'✅ 可以发' if passed else '❌ 不可发布'}（BLOCK {len(blockers)} / WARN {len(warns)}）")
    print(f"precheck: 已写入 {path.name}")
    emit(
        {
            "artifacts": [{"path": str(path), "kind": "markdown", "name": path.name}],
            "summary": "可以发" if passed else f"不可发布（{len(blockers)} 项 BLOCK）",
            "passed": passed,
            "items": items,
            "blocked": bool(blockers),
            "result_markdown": f"## 结论\n\n{'✅ 可以发' if passed else '❌ 不可发布'}\n\n{rows}",
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
