---
id: framework
name: 文章框架法
layer: 制作
maturity: v1
trigger: 当你说「用 PAS 写」「AIDA 框架」「结构化成文」时使用
cost: AI · 按对话计
required_keys: []
params:
  - {key: topic, label: 主题/素材要点, default: ""}
  - {key: framework, label: PAS/AIDA/BAB/STAR/SLAY, default: "PAS"}
outputs: [markdown]
paid: false
---

# 文章框架法

五种经典框架结构化成文（框架定义固定，不自由发挥）：

| 框架 | 段落 | 适用 |
|---|---|---|
| PAS | Problem 痛点 → Agitate 放大 → Solution 方案 | 卖点文/干货 |
| AIDA | Attention 注意 → Interest 兴趣 → Desire 欲望 → Action 行动 | 种草/推广 |
| BAB | Before 之前 → After 之后 → Bridge 桥梁 | 对比/ transformation |
| STAR | Situation 背景 → Task 任务 → Action 行动 → Result 结果 | 复盘/案例 |
| SLAY | Story 故事 → Lesson 教训 → Action 行动 → Yes 共鸣 | 个人成长/观点 |

规则：按所选框架出 `##` 段（段名含框架段关键词）；每段先给「这段要完成的
说服任务」一句，再写正文；素材不足的段落如实标「缺素材：需要 XX」，不编案例。
framework 不在五种内就列出可选值反问。
