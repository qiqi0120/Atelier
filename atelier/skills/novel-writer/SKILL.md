---
id: novel-writer
name: 小说创作
layer: 制作
maturity: v0
trigger: 当你说「写小说」「连载」「写第一章」时使用
cost: AI · 按对话计
required_keys: []
params:
  - {key: genre, label: 题材（如 都市异能/科幻悬疑）, default: ""}
  - {key: mode, label: bible（圣经）/chapter（章节）, default: "bible"}
outputs: [markdown]
paid: false
---

# 小说创作（v0）

三级流程（严格按序）：

1. `mode=bible`（第一轮交付）：世界观设定 / 主要人物卡（姓名·性格·欲望·恐惧）/
   三级大纲（全书弧 → 卷 → 章，每章一句话）/ 核心冲突与悬念表
2. `mode=chapter`（之后每次一章）：开头先复述本章用到的设定（人物/伏笔编号），
   再写正文 2000~4000 字；对不上设定处标「⚠️ 偏离」给修正选项，不悄悄改
3. 用户给的 genre 为空就反问；伏笔在圣经里编号（V1/V2…），回收时注明编号
