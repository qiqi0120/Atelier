---
id: asr
name: 语音识别
layer: 制作
maturity: v1
trigger: 当你说「转写字幕」「音频转文字」「出 SRT」时使用
cost: 按量计费 · 需密钥
required_keys: [ASR_API_KEY]
params:
  - {key: audio, label: 音频/视频路径, default: ""}
  - {key: format, label: 输出 srt/txt/json, default: "srt"}
  - {key: language, label: 语言（可选，如 zh）, default: ""}
outputs: [json]
paid: true
---

# 语音识别

云端转写（whisper 兼容 `/audio/transcriptions`，verbose_json 带时间段）→
SRT / TXT / JSON 字幕。未配置 `ASR_API_KEY` 时 409。视频文件同样可传
（服务端抽音轨）；本机没有 ffmpeg 时不能先抽轨，长视频建议先给音频。
