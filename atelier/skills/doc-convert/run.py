#!/usr/bin/env python3
"""doc-convert · Markdown → 自包含 HTML（F-F50）。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from atelier.server.visual import svgkit as sk

STYLE = """
body{max-width:760px;margin:40px auto;padding:0 20px;font-family:PingFang SC,Microsoft YaHei,sans-serif;
     color:#292524;line-height:1.75;font-size:15px}
h1{font-size:26px;border-bottom:2px solid #10b981;padding-bottom:8px}
h2{font-size:20px;margin-top:2em} h3{font-size:17px}
code{background:#F1F5F9;padding:2px 6px;border-radius:4px;font-size:0.9em}
pre{background:#1C1917;color:#E7E5E4;padding:14px;border-radius:10px;overflow:auto}
pre code{background:none;color:inherit}
table{border-collapse:collapse;width:100%} th,td{border:1px solid #D6D3D1;padding:6px 10px;text-align:left}
th{background:#F1F5F9} blockquote{border-left:4px solid #10b981;margin:0;padding:2px 14px;color:#57534E;background:#F0FDF4}
img{max-width:100%}
@media print{body{margin:0}}
"""


def main() -> int:
    params, out, _ = sk.skill_argv(desc="doc-convert")
    raw = str(sk.load_params(params, "markdown", required=True, label="Markdown") or "").strip()
    p = Path(raw.splitlines()[0].strip())
    if p.exists() and p.suffix.lower() in (".md", ".markdown"):
        raw = p.read_text(encoding="utf-8")
    if not raw:
        print("doc-convert: Markdown 内容为空", file=sys.stderr)
        return 2
    from markdown_it import MarkdownIt

    body = MarkdownIt("commonmark", {"typographer": True}).enable("table").render(raw)
    m = re.search(r"<h1>(.*?)</h1>", body)
    title = str(params.get("title") or "").strip() or (re.sub(r"<.*?>", "", m.group(1)) if m else "文档")

    out.mkdir(parents=True, exist_ok=True)
    dst = out / f"{sk.slugify(title)}.html"
    dst.write_text(
        f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{sk.esc(title)}</title><style>{STYLE}</style></head>"
        f'<body>{body}<hr><p style="color:#999;font-size:12px">由 Atelier doc-convert 生成 · '
        f'要 PDF：浏览器打开本文件 → 打印 → 存为 PDF</p></body></html>',
        encoding="utf-8",
    )
    print(f"doc-convert: {len(raw)} 字 MD → {dst.name}")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "html", "name": dst.name}],
        "summary": f"MD → HTML（{len(raw)} 字）",
        "result_markdown": (
            "转换完成：自包含 HTML（内联样式，可直接发或存档）。PDF/长图需要浏览器渲染引擎，"
            "本仓库不内置——用系统打印存 PDF 即可（产物页脚有说明），如实说明不做假装导出。"
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
