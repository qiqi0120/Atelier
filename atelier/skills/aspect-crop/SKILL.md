---
id: aspect-crop
name: 横竖版转换
layer: 制作
maturity: v1
trigger: 当你说「横转竖」「9:16」「16:9」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: video, label: 视频路径, default: ""}
  - {key: target, label: 目标画幅 vertical(9:16)/horizontal(16:9), default: "vertical"}
  - {key: mode, label: crop（中心裁剪）/blur（模糊垫底）, default: "blur"}
outputs: [video]
paid: false
---

# 横竖版转换

16:9 ↔ 9:16。`crop` 中心裁剪（主体居中才用）；`blur` 保全景、上下/左右垫
模糊放大背景（口播/演示类推荐）。依赖 ffmpeg。
