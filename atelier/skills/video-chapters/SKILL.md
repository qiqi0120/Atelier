---
id: video-chapters
name: 视频章节
layer: 制作
maturity: v1
trigger: 当你说「视频分P」「出章节目录」「时间戳目录」时使用
cost: AI · 按对话计
required_keys: []
params:
  - {key: transcript, label: '转录文本（可带 [mm:ss] 时间戳；没有就用 asr 技能先转写）, default: ""'}
  - {key: style, label: '目录风格 brief/detailed, default: "brief"'}
outputs: [markdown]
paid: false
---

# 视频章节

转录文本 → 章节时间戳目录。规则：

1. 有时间戳：按 `[mm:ss]` 或 `mm:ss` 定位章节边界；没有时间戳就如实说明
   「无法定位时间」，只输出无时间戳的章节大纲，并建议先跑 asr 技能
2. `brief`：5~9 章，每章一行 `mm:ss 章节名（≤12字）`；`detailed`：每章下加 1~2 行要点
3. 章节名从内容里提炼，**不编造文本里没有的主题**；时长分布明显不均时按内容自然分段
4. 输出 B 站/YouTube 通用的章节格式（首行 `00:00 开场`），可直接粘贴
5. 转录文本为空就反问，不要编目录
