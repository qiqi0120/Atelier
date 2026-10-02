---
id: chroma-key
name: 绿幕抠像
layer: 制作
maturity: v1
trigger: 当你说「抠图」「绿幕去背景」「换背景」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: image, label: '绿/蓝幕图片路径, default: ""'}
  - {key: key_color, label: '幕色 green/blue, default: "green"'}
  - {key: tolerance, label: '色距容差 10~120, default: "60"'}
  - {key: background, label: '新背景（纯色如 #FFE8D6 或图片路径；缺省透明）, default: ""'}
outputs: [image]
paid: false
---

# 绿幕抠像

色距抠像（绿/蓝幕）→ 透明 PNG，可换纯色或图片背景。**诚实说明**：色距抠像
只对纯色幕布效果好；复杂前景（发丝/半透明）或非绿蓝背景请用专业工具（本仓库
暂无语义分割模型，见 SPEC-13 §6）。
