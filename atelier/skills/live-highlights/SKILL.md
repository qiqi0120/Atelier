---
id: live-highlights
name: 直播高光
layer: 制作
maturity: v1
trigger: 当你说「直播录像切片」「直播高光」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: video, label: 直播录像路径, default: ""}
  - {key: count, label: 要几段（默认 5）, default: "5"}
  - {key: duration, label: 每段秒数（默认 60）, default: "60"}
outputs: [video]
paid: false
---

# 直播高光

直播录像按「说话最密集」找高能段切片（silencedetect 反推，与 clip-cut 的
energy 模式同源；独立成技能是因为直播录像默认参数不同：段更长、段数更多）。
依赖 ffmpeg。找的依据是音量密度，**看不懂内容**——弹幕里的高光还得你自己标。
