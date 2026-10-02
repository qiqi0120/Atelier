---
id: img-enhance
name: 图像增强
layer: 制作
maturity: v1
trigger: 当你说「图放清晰点」「图片增强」「放大图片」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: image, label: 图片路径, default: ""}
  - {key: scale, label: 放大倍数（1~4）, default: "2"}
  - {key: denoise, label: 降噪 mild/strong/off, default: "mild"}
  - {key: sharpen, label: 锐化 0~100, default: "60"}
outputs: [image]
paid: false
---

# 图像增强

LANCZOS 放大 + 中值降噪 + UnsharpMask 锐化（Pillow）。

**诚实说明**：这是传统算法增强，**不是 AI 超分**——文字/图形类效果好，
人像照片放大 4 倍以上不如专门超分模型。参数给重了会出噪点 halo，宁轻勿重。
