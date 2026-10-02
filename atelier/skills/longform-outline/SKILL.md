---
id: longform-outline
name: 长文大纲
layer: 制作
maturity: v1
trigger: 当你说「长文大纲」「万字文框架」时使用
cost: AI · 按对话计
required_keys: []
params:
  - {key: topic, label: 主题, default: ""}
  - {key: target_words, label: 目标字数（默认 6000）, default: "6000"}
outputs: [markdown]
paid: false
---

# 长文大纲

主题 → 可直接开写的 H2/H3 大纲。规则：

1. 结构：`##` 大节 4~7 个、每节下 `###` 小节 2~4 个；每节标注建议字数，
   **各节字数加总 = 目标字数**（±10%）
2. 每个小节一句话写清「这节论证什么 / 给读者什么」；需要图表的位置标
   「📊 图表位：建议画什么」（不给假数据）
3. 文末附 FAQ：读者最可能的 3~5 个疑问 + 一句话答法
4. topic 为空反问；目标字数 <1500 时建议改用普通文章结构，别硬套长文
