---
id: doc-convert
name: 文档转换
layer: 制作
maturity: v1
trigger: 当你说「MD 转 HTML」「导出网页」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: markdown, label: Markdown 文本或 .md 路径, default: ""}
  - {key: title, label: 文档标题（可选，缺省取首个 H1）, default: ""}
outputs: [html]
paid: false
---

# 文档转换

Markdown → 自包含 HTML（markdown-it-py 渲染 + 内联样式，可打印）。
**诚实说明**：PDF/长图导出需要浏览器渲染引擎（本仓库不内置），要 PDF 请用
系统「打印 → 存为 PDF」打开产物 HTML 即可——不假装直接出 PDF。
