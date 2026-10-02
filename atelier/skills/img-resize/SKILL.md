---
id: img-resize
name: 尺寸/格式/压缩
layer: 制作
maturity: v1
trigger: 当你说「改图片尺寸」「压到 500KB 以内」「转成 webp」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: image, label: '图片路径, default: ""'}
  - {key: width, label: '目标宽（可选）, default: ""'}
  - {key: height, label: '目标高（可选）, default: ""'}
  - {key: mode, label: 'resize/cover/pad, default: "resize"'}
  - {key: bg, label: 'pad 底色（如 #FFFFFF）, default: "#FFFFFF"'}
  - {key: format, label: '输出 png/jpeg/webp（可选，缺省保原格式）, default: ""'}
  - {key: target_kb, label: '压到目标 KB（可选）, default: ""'}
outputs: [image]
paid: false
---

# 尺寸/格式/压缩

改尺寸（resize 等比 / cover 中心裁剪填满 / pad 补边）/ 转格式 / 压到目标大小
（JPEG/Webp 质量二分，压不进目标会如实报告最优点，不硬塞）。
