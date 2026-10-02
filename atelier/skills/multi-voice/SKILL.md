---
id: multi-voice
name: 多角色配音
layer: 制作
maturity: v1
trigger: 当你说「多角色配音」「对话配音」时使用
cost: 按量计费 · 需密钥
required_keys: [TTS_API_KEY]
params:
  - {key: script, label: '台词（每行「角色|台词」，如 旁白|开场了）, default: ""'}
  - {key: voices, label: '角色→音色 JSON {"旁白":"alloy","小王":"echo"}（未分配的用默认）, default: ""'}
outputs: [audio]
paid: true
---

# 多角色配音

按角色分配音色逐段合成。拼接策略（如实执行）：WAV 用标准库无损拼接；
TTS 返回 mp3 时需要 ffmpeg 合并——本机没有 ffmpeg 就交付分段文件 + 合并命令，
**不假装已经拼好**。
