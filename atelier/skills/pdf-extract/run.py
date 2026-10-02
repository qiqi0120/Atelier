#!/usr/bin/env python3
"""pdf-extract · pypdf 文本抽取（F-F45 前置）。"""

from __future__ import annotations

import sys
from pathlib import Path

from atelier.server.visual import svgkit as sk


def main() -> int:
    params, out, _ = sk.skill_argv(desc="pdf-extract")
    src = str(sk.load_params(params, "pdf", required=True, label="PDF 路径") or "").strip()
    path = Path(src)
    if not path.exists():
        print(f"pdf-extract: 文件不存在：{src}", file=sys.stderr)
        return 2
    try:
        max_pages = min(200, max(1, int(params.get("max_pages") or 40)))
    except (TypeError, ValueError):
        max_pages = 40
    try:
        from pypdf import PdfReader
    except ImportError:
        print("pdf-extract: 缺少 pypdf（uv pip install -e . 重装依赖）", file=sys.stderr)
        return 2
    try:
        reader = PdfReader(str(path))
    except OSError as e:
        print(f"pdf-extract: PDF 打不开（{type(e).__name__}: {e}）", file=sys.stderr)
        return 2
    except ValueError as e:  # pypdf 对损坏文件抛 ValueError 子类
        print(f"pdf-extract: PDF 损坏无法解析（{e}）", file=sys.stderr)
        return 2
    total = len(reader.pages)
    if total == 0:
        print("pdf-extract: 空 PDF", file=sys.stderr)
        return 2
    pages = []
    empty_pages = 0
    for i, page in enumerate(reader.pages[:max_pages]):
        text = (page.extract_text() or "").strip()
        if not text:
            empty_pages += 1
            text = "（本页无文本层——可能是扫描图，OCR 不在本技能能力内，如实标注）"
        pages.append(f"--- 第 {i+1} 页 ---\n\n{text}")
    if total > max_pages:
        print(f"pdf-extract: 全文 {total} 页，只抽了前 {max_pages} 页（max_pages 限制）", file=sys.stderr)

    out.mkdir(parents=True, exist_ok=True)
    dst = out / f"{path.stem}-extract.md"
    dst.write_text("\n\n".join(pages), encoding="utf-8")
    chars = sum(len(p) for p in pages)
    print(f"pdf-extract: {min(total, max_pages)}/{total} 页，{chars} 字")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "markdown", "name": dst.name}],
        "summary": f"抽取 {min(total, max_pages)}/{total} 页 · {chars} 字",
        "result_markdown": (
            f"抽取完成：{min(total, max_pages)}/{total} 页，{chars} 字，页码已标记。\n"
            + (f"- ⚠️ {empty_pages} 页无文本层（扫描图/纯图页），已如实标注\n" if empty_pages else "")
            + "- 公式与图表不还原排版（纯文本抽取）\n"
            "- 下一步：把本文件喂给 paper-read 技能出解读"
        ),
        "pages": min(total, max_pages),
        "empty_pages": empty_pages,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
