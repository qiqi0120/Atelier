---
id: album-video
name: 相册视频
layer: 制作
maturity: v1
trigger: 当你说「图片做视频」「相册视频」「Ken Burns」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: images, label: 图片路径（每行一个，按顺序）, default: ""}
  - {key: per_image, label: 每张秒数（默认 3）, default: "3"}
  - {key: size, label: 画幅 1080x1920 / 1920x1080 / 1080x1080, default: "1080x1920"}
  - {key: audio, label: 背景音乐路径（可选）, default: ""}
outputs: [video]
paid: false
---

# 相册视频

图片序列 + Ken Burns 缓动（zoompan）+ 交叉淡化 + 可挂 BGM → mp4。
依赖 ffmpeg。图片 ≥2 张。
