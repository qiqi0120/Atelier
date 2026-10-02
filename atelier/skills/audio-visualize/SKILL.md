---
id: audio-visualize
name: 音频可视化
layer: 制作
maturity: v1
trigger: 当你说「音频波形图」「声音可视化」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: audio, label: 音频路径, default: ""}
  - {key: width, label: 宽（默认 1600）, default: "1600"}
  - {key: height, label: 高（默认 400）, default: "400"}
outputs: [image]
paid: false
---

# 音频可视化

纯音频 → 波形图 PNG（ffmpeg showwavespic）。动图/频谱视频模式依赖 ffmpeg 的
完整滤镜链，本版交付静态波形（如实说明）；要视频配 BGM 请用相册视频技能挂音频。
