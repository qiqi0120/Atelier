---
id: tts
name: 文字转语音
layer: 制作
maturity: v1
trigger: 当你说「配音」「文字转语音」「TTS」时使用
cost: 按量计费 · 需密钥
required_keys: [TTS_API_KEY]
params:
  - {key: text, label: 要读的文本, default: ""}
  - {key: voice, label: 音色（如 alloy/echo，看你的服务商）, default: "alloy"}
  - {key: speed, label: 语速 0.5~2.0, default: "1.0"}
outputs: [audio]
paid: true
---

# 文字转语音

云端 TTS（OpenAI 兼容 `/audio/speech` 接口约定）→ mp3。未配置 `TTS_API_KEY`
时运行按钮禁用、接口 409 明确告知缺什么。可用 `TTS_BASE_URL` 指到兼容服务商。
文本 ≤ 4000 字（更长请分段，接口限制如实转述）。
