---
id: beat-cut
name: 音乐卡点
layer: 制作
maturity: v1
trigger: 当你说「卡点视频」「踩点切换」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: images, label: 图片路径（每行一个，按顺序）, default: ""}
  - {key: audio, label: 音乐路径, default: ""}
  - {key: bpm, label: 音乐 BPM（如 120）, default: "120"}
  - {key: beats_per_cut, label: 几拍切一张（默认 4）, default: "4"}
outputs: [video]
paid: false
---

# 音乐卡点

图片按 BPM 网格踩点切换。**诚实说明**：真实节拍检测需要额外工具（aubio 等），
本技能按你给的 BPM 均分拍点——对节拍清晰的电子/流行乐够用；鼓点复杂的歌
请先确认 BPM 或用 beats_per_cut 调整密度。依赖 ffmpeg。
