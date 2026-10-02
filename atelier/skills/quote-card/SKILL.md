---
id: quote-card
name: 金句卡
layer: 制作
maturity: v1
trigger: 当你说「做张金句卡」「把这句话做成卡片」「数据卡」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: quote, label: 金句原文, default: ""}
  - {key: attribution, label: 署名（可选）, default: ""}
  - {key: theme, label: 色板 warm/cool/fresh/ink, default: "warm"}
  - {key: dataset, label: 数据对（可选，逗号分隔 名:值）, default: ""}
outputs: [image]
paid: false
---

# 金句卡

16:9 横版（1920×1080）金句卡 / 数据卡，确定性排版，产出 SVG + HTML 预览。

## 用法

1. `quote` 贴一句 ≤80 字的金句（超长会被截断并如实提示）
2. 可选 `attribution` 署名；可选 `dataset`（如 `完播率:38%,涨粉:1.2w`）自动变成底部数据条
3. `theme` 四套色板：warm 暖 / cool 冷 / fresh 绿 / ink 素

脚本只做排版，**不改写你的句子**；要润色先在对话里让 AI 改，再回来出卡。
产出后看 result_markdown 里的「视觉质检」段，有告警按建议调参重跑。
