---
id: meme
name: 表情包
layer: 制作
maturity: v1
trigger: 当你说「做张梗图」「上下大字表情包」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: top_text, label: 上方大字, default: ""}
  - {key: bottom_text, label: 下方大字, default: ""}
  - {key: base_image, label: 底图路径（可选，无则纯色底）, default: ""}
  - {key: theme, label: 纯色底色板 warm/cool/fresh/ink, default: "ink"}
outputs: [image]
paid: false
---

# 表情包

上下大字梗图（800×800 PNG，Pillow 绘制）。给了 `base_image` 就在图上下压字；
没给就出纯色底版本。「反应图」用法：只填 `bottom_text`。
