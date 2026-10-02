---
id: data-report
name: 数据报告
layer: 制作
maturity: v1
trigger: 当你说「数据报告」「分析这组数据」「CSV 出报告」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: data, label: 数据（CSV 文本/路径；JSON 对象数组也行）, default: ""}
  - {key: title, label: 报告标题（可选）, default: ""}
outputs: [markdown]
paid: false
---

# 数据报告

CSV/JSON → KPI 统计表 + SVG 柱状/折线图 + Markdown 报告页。
**统计全部由脚本计算**（count/sum/mean/min/max/分布），AI 不参与数值；
「洞察」段留白并提示接对话让 AI 解读（基于真实统计，不编）。数值列自动识别，
文本列给出频次 Top3。
