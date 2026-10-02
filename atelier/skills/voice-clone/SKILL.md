---
id: voice-clone
name: 声音克隆
layer: 制作
maturity: v0
trigger: 当你说「克隆我的声音」「复刻音色」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: sample, label: 参考音频路径（wav）, default: ""}
outputs: [markdown]
paid: false
---

# 声音克隆（v0 · 准备工具）

**诚实声明**：声音克隆需要专门的供应商 API，本仓库**尚未接入**任何一家。
本技能现在做的是接入前的准备：检查参考音频质量（时长/声道/大小）+ 生成
音色需求单，让你在选定供应商后一次配好。不做假克隆。
