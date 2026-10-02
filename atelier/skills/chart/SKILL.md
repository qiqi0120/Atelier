---
id: chart
name: 图表可视化
layer: 制作
maturity: v1
trigger: 当你说「画个图表」「把这组数据可视化」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: type, label: '类型 bar/hbar/line/area/pie/donut/scatter/radar/funnel, default: "bar"'}
  - {key: series, label: '数据 JSON（如 {"周一":12,"周二":18} 或 [{"name":"x","value":3}]）, default: ""'}
  - {key: title, label: '图表标题（可选）, default: ""'}
  - {key: theme, label: '色板, default: "cool"'}
outputs: [image]
paid: false
---

# 图表可视化

数据 → SVG 图表。**统计由脚本从你给的数据算**，AI 不参与数值（不编数）。

本版支持 9 类：柱状 bar / 横条 hbar / 折线 line / 面积 area / 饼 pie / 环 donut /
散点 scatter / 雷达 radar / 漏斗 funnel（PRD 全量 25+ 类按需增量，如实说明）。

`series` 传 JSON：对象（名→数值）或数组（`[{"name":"..","value":n}]`）；
radar 支持多组 `[{"name":"A","values":[1,2,3]}]` + `labels` 参数。
