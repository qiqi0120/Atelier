---
id: intro-outro
name: 片头片尾
layer: 制作
maturity: v1
trigger: 当你说「加片头」「加片尾」「片头卡」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: video, label: 正片路径, default: ""}
  - {key: title, label: 片头标题, default: ""}
  - {key: subtitle, label: 片头副题（可选）, default: ""}
  - {key: outro_text, label: 片尾文字（可选，缺省不出片尾）, default: ""}
  - {key: duration, label: 片头秒数（默认 2）, default: "2"}
outputs: [video]
paid: false
---

# 片头片尾

Pillow 画片头/片尾卡 → ffmpeg 拼进正片头尾（淡入淡出）。依赖 ffmpeg。
