---
id: infographic
name: 信息图
layer: 制作
maturity: v1
trigger: 当你说「做张信息图」「长图排版」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: title, label: '大标题, default: ""'}
  - {key: sections, label: '分节 JSON [{"heading":"..","points":[".."],"metric":".."}], default: ""'}
  - {key: theme, label: '色板, default: "fresh"'}
outputs: [image]
paid: false
---

# 信息图

竖版信息长图（1080 宽，高度按分节自适应），分节标题 + 要点列表 + 数据高亮位。

**诚实说明**：PRD 的「动画 GIF 模式」本版不支持——本技能出静态长图；要动效请把
分节拆成多帧在视频工具里做（避免假装能一键 GIF）。文案只排版不改写。
