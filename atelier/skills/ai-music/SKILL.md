---
id: ai-music
name: AI 音乐
layer: 制作
maturity: v0
trigger: 当你说「来段 BGM」「配乐」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: mood, label: 情绪（如 温暖/紧张/治愈）, default: "温暖"}
  - {key: duration, label: 时长（秒）, default: "30"}
  - {key: scene, label: 用在哪（口播背景/vlog/卡点）, default: "口播背景"}
outputs: [markdown]
paid: false
---

# AI 音乐（v0 · 需求单）

**诚实声明**：生成原创 BGM 需要专门的音乐生成服务，本仓库**尚未接入**。
本技能现在生成一份可直接投给任意音乐生成工具（Suno/天工等）的**完整需求单**：
风格描述、结构、时长、参考曲目要素、与口播的混音建议。不假装能出音频。
