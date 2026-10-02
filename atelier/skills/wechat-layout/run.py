#!/usr/bin/env python3
"""wechat-layout · Markdown → 公众号内联样式 HTML（零依赖）。"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path

THEMES = {
    "default": {
        "body": "font-size:16px;line-height:1.75;color:#3f3f3f;letter-spacing:0.5px;word-break:break-word;",
        "h2": "font-size:19px;font-weight:600;color:#1a1a1a;margin:28px 0 14px;padding-left:10px;border-left:4px solid #576b95;",
        "h3": "font-size:17px;font-weight:600;color:#1a1a1a;margin:24px 0 12px;",
        "p": "margin:0 0 1.1em 0;",
        "quote": "border-left:3px solid #d0d0d0;background:#f7f7f7;padding:10px 14px;margin:16px 0;color:#5a5a5a;",
        "code": "font-family:Menlo,Consolas,monospace;font-size:14px;background:#f2f3f5;padding:2px 5px;border-radius:3px;",
        "pre": "font-family:Menlo,Consolas,monospace;font-size:13px;background:#f7f8fa;padding:14px;border-radius:6px;overflow-x:auto;line-height:1.6;",
        "a": "color:#576b95;text-decoration:none;",
        "li": "margin:0 0 0.5em 0;line-height:1.75;",
        "hr": "border:none;border-top:1px solid #e8e8e8;margin:26px 0;",
    },
    "clean": {
        "body": "font-size:16px;line-height:1.8;color:#222;word-break:break-word;",
        "h2": "font-size:20px;font-weight:600;color:#111;margin:30px 0 14px;",
        "h3": "font-size:17px;font-weight:600;color:#222;margin:24px 0 12px;",
        "p": "margin:0 0 1.2em 0;",
        "quote": "border-left:3px solid #07c160;background:#f6fffa;padding:10px 14px;margin:16px 0;color:#333;",
        "code": "font-family:Menlo,Consolas,monospace;font-size:14px;background:#f2f3f5;padding:2px 5px;border-radius:3px;",
        "pre": "font-family:Menlo,Consolas,monospace;font-size:13px;background:#f7f8fa;padding:14px;border-radius:6px;overflow-x:auto;",
        "a": "color:#07c160;text-decoration:none;",
        "li": "margin:0 0 0.5em 0;",
        "hr": "border:none;border-top:1px solid #e8e8e8;margin:26px 0;",
    },
    "warm": {
        "body": "font-size:16px;line-height:1.85;color:#4a3f35;word-break:break-word;",
        "h2": "font-size:19px;font-weight:600;color:#3a2f26;margin:28px 0 14px;",
        "h3": "font-size:17px;font-weight:600;color:#3a2f26;margin:24px 0 12px;",
        "p": "margin:0 0 1.15em 0;",
        "quote": "border-left:3px solid #c8a06a;background:#fdf6ec;padding:10px 14px;margin:16px 0;color:#6b5744;",
        "code": "font-family:Menlo,Consolas,monospace;font-size:14px;background:#f5efe6;padding:2px 5px;border-radius:3px;",
        "pre": "font-family:Menlo,Consolas,monospace;font-size:13px;background:#f5efe6;padding:14px;border-radius:6px;overflow-x:auto;",
        "a": "color:#a8763e;text-decoration:none;",
        "li": "margin:0 0 0.5em 0;",
        "hr": "border:none;border-top:1px dashed #d8cbb8;margin:26px 0;",
    },
}

INLINE = [
    (re.compile(r"`([^`]+)`"), lambda m: f'<code style="{THEME["code"]}">{html.escape(m.group(1))}</code>'),
    (re.compile(r"\*\*([^*]+)\*\*"), lambda m: f"<strong>{html.escape(m.group(1))}</strong>"),
    (re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)"), lambda m: f"<em>{html.escape(m.group(1))}</em>"),
    (
        re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)"),
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}" style="{THEME["a"]}">{html.escape(m.group(1))}</a>',
    ),
]
THEME: dict[str, str] = THEMES["default"]

# 提到模块级：f-string 表达式内不能含反斜杠（Python 3.10 语法限制）
RE_H = re.compile(r"^\s{0,3}#{1,6}\s+")
RE_H_COUNT = re.compile(r"^(#+) ")
RE_H_STRIP = re.compile(r"^#+\s+")
RE_HR = re.compile(r"^\s{0,3}(-{3,}|\*{3,})\s*$")
RE_UL = re.compile(r"^\s*[-*+]\s+")
RE_UL_STRIP = re.compile(r"^\s*[-*+]\s+")
RE_OL = re.compile(r"^\s*\d+[.)]\s+")
RE_OL_STRIP = re.compile(r"^\s*\d+[.)]\s+")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="wechat-layout")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--out", default=os.environ.get("ATELIER_OUT", "."))
    ap.add_argument("--project", default=os.environ.get("ATELIER_PROJECT", "default"))
    return ap.parse_args(argv)


def emit(payload: dict) -> None:
    sys.stdout.write("ATELIER_RESULT " + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    for pat, fn in INLINE:
        text = pat.sub(fn, text)
    return text


def convert(md: str, theme_name: str) -> tuple[str, list[str]]:
    global THEME
    THEME = THEMES[theme_name]
    unsupported: list[str] = []
    out: list[str] = []
    lines = md.replace("\r\n", "\n").split("\n")
    i = 0
    in_ul = in_ol = in_code = False
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                if in_ul or in_ol:
                    out.append("</ul>" if in_ul else "</ol>")
                    in_ul = in_ol = False
                out.append(f'<pre style="{THEME["pre"]}"><code>')
                in_code = True
            i += 1
            continue
        if in_code:
            out.append(html.escape(line, quote=False))
            i += 1
            continue
        if line.strip().startswith("|"):
            unsupported.append(f"第 {i + 1} 行：表格语法未支持，请转成图片或列表")
            i += 1
            continue
        if line.strip().startswith("<!--"):
            unsupported.append(f"第 {i + 1} 行：HTML 注释被丢弃")
            i += 1
            continue
        if RE_H.match(line):
            if in_ul or in_ol:
                out.append("</ul>" if in_ul else "</ol>")
                in_ul = in_ol = False
            level = len(RE_H_COUNT.match(line).group(1))
            content = inline(RE_H_STRIP.sub("", line).strip())
            style = THEME["h2"] if level <= 2 else THEME["h3"]
            tag = "h1" if level == 1 else ("h2" if level == 2 else "h3")
            out.append(f'<{tag} style="{style}">{content}</{tag}>')
            i += 1
            continue
        if RE_HR.match(line):
            if in_ul or in_ol:
                out.append("</ul>" if in_ul else "</ol>")
                in_ul = in_ol = False
            out.append(f'<hr style="{THEME["hr"]}"/>')
            i += 1
            continue
        if RE_UL.match(line):
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append('<ul style="padding-left:1.2em;margin:0 0 1.1em 0;">')
                in_ul = True
            out.append(f'<li style="{THEME["li"]}">{inline(RE_UL_STRIP.sub("", line))}</li>')
            i += 1
            continue
        if RE_OL.match(line):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append('<ol style="padding-left:1.4em;margin:0 0 1.1em 0;">')
                in_ol = True
            out.append(f'<li style="{THEME["li"]}">{inline(RE_OL_STRIP.sub("", line))}</li>')
            i += 1
            continue
        if line.lstrip().startswith("> "):
            if in_ul or in_ol:
                out.append("</ul>" if in_ul else "</ol>")
                in_ul = in_ol = False
            out.append(f'<blockquote style="{THEME["quote"]}">{inline(line.lstrip()[2:])}</blockquote>')
            i += 1
            continue
        if not line.strip():
            i += 1
            continue
        if in_ul or in_ol:
            out.append("</ul>" if in_ul else "</ol>")
            in_ul = in_ol = False
        out.append(f'<p style="{THEME["p"]}">{inline(line.strip())}</p>')
        i += 1
    if in_code:
        out.append("</code></pre>")
    if in_ul or in_ol:
        out.append("</ul>" if in_ul else "</ol>")
    return "\n".join(out), unsupported


def slugify(text: str) -> str:
    s = "".join(c.lower() if c.isascii() and c.isalnum() else "-" for c in text[:20]).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s or "article"


def main(argv: list[str] | None = None) -> int:
    global THEME
    args = parse_args(argv)
    try:
        params = json.loads(args.params or "{}")
    except json.JSONDecodeError as e:
        print(f"wechat-layout: --params 不是合法 JSON：{e}", file=sys.stderr)
        return 2
    md = str(params.get("markdown") or "").strip()
    if not md:
        print("wechat-layout: markdown 为空，不产出空文件", file=sys.stderr)
        return 2
    theme_name = str(params.get("theme") or "default")
    if theme_name not in THEMES:
        print(f"wechat-layout: theme 非法 {theme_name!r}，可选 {sorted(THEMES)}", file=sys.stderr)
        return 2
    body, unsupported = convert(md, theme_name)
    if str(params.get("inline_css", "true")).lower() in ("false", "0", "no"):
        print("wechat-layout: WARNING 公众号会剥离 <style>/class，已强制内联", file=sys.stderr)
    THEME = THEMES[theme_name]
    doc = (
        "<!doctype html>\n<html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(md.splitlines()[0][:30])}</title></head>"
        f'<body style="margin:0;padding:16px;background:#fff;">'
        f'<section style="{THEME["body"]}">{body}</section></body></html>'
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    slug = slugify(md)
    hp = out / f"{slug}.html"
    mp = out / f"{slug}.md"
    hp.write_text(doc, encoding="utf-8")
    mp.write_text(md, encoding="utf-8")
    if unsupported:
        print(f"wechat-layout: {len(unsupported)} 处未支持语法已记录：{unsupported[0]}", file=sys.stderr)
    print(f"wechat-layout: 已生成 {hp.name}（theme={theme_name}，全部内联样式）")
    print(f"wechat-layout: 原文副本 {mp.name}")
    emit(
        {
            "artifacts": [
                {"path": str(hp), "kind": "html", "name": hp.name},
                {"path": str(mp), "kind": "markdown", "name": mp.name},
            ],
            "summary": f"排版完成（{theme_name}）" + (f"，{len(unsupported)} 处未支持语法" if unsupported else ""),
            "unsupported": unsupported,
            "theme": theme_name,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
