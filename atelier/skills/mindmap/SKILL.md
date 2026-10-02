---
id: mindmap
name: 思维导图
layer: 制作
maturity: v1
trigger: 当你说「画思维导图」「把大纲变成导图」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: outline, label: 缩进大纲（每行一层，两空格缩进）, default: ""}
  - {key: theme, label: 色板, default: "warm"}
outputs: [image]
paid: false
---

# 思维导图

Markdown 缩进大纲 → SVG 思维导图 + **可折叠 HTML**（details/summary 交互版）。

输入示例：
```
内容体系
  选题
    爆款拆解
    日历建议
  制作
    卡片
```
第一行是根节点；缩进每两级一层，最多 4 层（更深的并入上一层并提示）。
