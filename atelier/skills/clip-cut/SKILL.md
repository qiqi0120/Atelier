---
id: clip-cut
name: 长视频切片
layer: 制作
maturity: v1
trigger: 当你说「切片」「切高光」「剪出精彩片段」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: video, label: 视频路径, default: ""}
  - {key: mode, label: points（给时间点）/energy（自动找高能段）, default: "energy"}
  - {key: points, label: 时间点（mode=points，逗号分隔秒或 分:秒，如 30,2:15）, default: ""}
  - {key: duration, label: 每段时长秒（默认 45）, default: "45"}
  - {key: count, label: energy 模式要几段（默认 3）, default: "3"}
outputs: [video]
paid: false
---

# 长视频切片

两种找点方式（如实说明）：
- `points`：你指定起点，脚本精确切（最可控）
- `energy`：ffmpeg silencedetect 反向找「说话最密集」的高能段（口播有效，
  对纯 BGM 视频意义有限——此时请用 points）
依赖本机 ffmpeg，缺失明确失败。
