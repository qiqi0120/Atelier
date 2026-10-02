---
id: pdf-extract
name: PDF 抽取
layer: 制作
maturity: v1
trigger: 当你说「抽 PDF 文字」「论文转文本」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: pdf, label: PDF 路径, default: ""}
  - {key: max_pages, label: 最多页数（默认 40）, default: "40"}
outputs: [markdown]
paid: false
---

# PDF 抽取

pypdf 抽取 PDF 文本 → 带 `--- 第 N 页 ---` 标记的 markdown，供 paper-read 技能
解读。**诚实说明**：纯文本抽取，不还原公式排版与图表（公式会乱码，扫描版
PDF 没有文本层——这两种情况会如实报告，不假装抽取成功）。
