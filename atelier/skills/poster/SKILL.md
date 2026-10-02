---
id: poster
name: 营销海报
layer: 制作
maturity: v1
trigger: 当你说「做张海报」「1080×1920 竖版海报」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: title, label: 主标题, default: ""}
  - {key: subtitle, label: 副标题, default: ""}
  - {key: bullets, label: 卖点（换行分隔）, default: ""}
  - {key: cta, label: 行动号召, default: "扫码了解"}
  - {key: theme, label: 色板 warm/cool/fresh/ink, default: "cool"}
outputs: [image]
paid: false
---

# 营销海报

1080×1920 竖版海报，确定性版式：主标题区 → 卖点条 → 行动区。SVG + HTML 预览。

脚本只排版不改文案；标题建议 ≤12 字一行（超长自动换行并提示）。看「视觉质检」段调参重跑。
