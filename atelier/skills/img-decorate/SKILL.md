---
id: img-decorate
name: 水印/圆角/拼接
layer: 制作
maturity: v1
trigger: 当你说「加水印」「图片拼长图」「圆角处理」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: images, label: 图片路径（多个用换行分隔）, default: ""}
  - {key: op, label: watermark/round/stack, default: "watermark"}
  - {key: text, label: 水印文字（op=watermark 必填）, default: ""}
  - {key: tile, label: 水印平铺 single/tile, default: "tile"}
  - {key: opacity, label: 水印透明度 0~100, default: "18"}
  - {key: radius, label: 圆角半径 px（op=round）, default: "32"}
outputs: [image]
paid: false
---

# 水印/圆角/拼接

文字水印（平铺/单角，透明度可调）、圆角（透明 PNG）、多图纵向拼接（对齐最宽）。
`images` 每行一个路径；op=stack 至少 2 张。
