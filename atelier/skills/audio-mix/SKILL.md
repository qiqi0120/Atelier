---
id: audio-mix
name: 混音
layer: 制作
maturity: v1
trigger: 当你说「混音」「BGM 压低」「配音配乐合成」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: voice, label: 人声/主音轨路径, default: ""}
  - {key: bgm, label: BGM 路径, default: ""}
  - {key: bgm_volume, label: BGM 音量 0~1, default: "0.2"}
  - {key: duck, label: BGM 自动闪避 on/off, default: "on"}
outputs: [audio]
paid: false
---

# 混音

人声 + BGM 合成（ffmpeg amix）。`duck=on` 时 BGM 走 sidechain 压缩：人声出现
BGM 自动压低（真闪避，不是简单叠音量）。依赖本机 ffmpeg，缺失明确失败。
