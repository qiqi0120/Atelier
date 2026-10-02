---
id: compare
name: 对比图
layer: 制作
maturity: v1
trigger: 当你说「做张对比图」「A vs B」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: left, label: '左侧名（方案 A）, default: ""'}
  - {key: right, label: '右侧名（方案 B）, default: ""'}
  - {key: rows, label: '对比行 JSON [{"dim":"价格","left":"99","right":"199","win":"left"}], default: ""'}
  - {key: theme, label: '色板, default: "cool"'}
outputs: [image]
paid: false
---

# 对比图

A vs B 参数对照表（维度行 + 左右值 + 胜出高亮）。`rows.win` 可标 `left`/`right`
让胜出值加高亮底色；不标则中性展示。文案只排版不改写、不替你判断胜负。
