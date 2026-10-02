---
id: audio-denoise
name: 音频降噪
layer: 制作
maturity: v1
trigger: 当你说「音频降噪」「去电流声」「去风噪」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: audio, label: 音频路径, default: ""}
  - {key: strength, label: 降噪强度 mild/strong, default: "mild"}
outputs: [audio]
paid: false
---

# 音频降噪

ffmpeg `afftdn`（FFT 降噪）→ wav。**依赖本机 ffmpeg**：没装会明确失败并给
安装指引（brew install ffmpeg），不会含糊报错。
