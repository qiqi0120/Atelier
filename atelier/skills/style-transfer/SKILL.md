---
id: style-transfer
name: 风格迁移
layer: 制作
maturity: v0
trigger: 当你说「严肃点改成搞笑」「书面改成口语」「换个语气」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: text, label: 原文, default: ""}
  - {key: from_style, label: 原风格, default: "serious"}
  - {key: to_style, label: 目标风格, default: "colloquial"}
  - {key: platform, label: 平台, default: "xhs"}
outputs: [markdown]
paid: false
---

# 风格迁移

按目标语气重写同一段内容，**信息量不许变**。

支持的目标风格：

| to_style | 特征 | 适合 |
|---|---|---|
| `colloquial` | 书面→口语：所以/但/特别/我觉得 | 小红书、微博 |
| `funny` | 严肃→搞笑：加夸张副词、反问、去名词化 | 娱乐向短视频口播 |
| `pro` | 平实→专业：术语前置、限定条件显式化 | 公众号、知乎 |
| `warm` | 冷淡→亲和：加共情前缀、称呼读者 | 私域、评论区互动 |
| `serious` | 搞笑→严肃：去梗、去夸张、回到陈述句 | 官方号、公告 |

## 执行

```bash
python atelier/skills/style-transfer/run.py \
  --params '{"text":"…","to_style":"colloquial","platform":"xhs"}' \
  --out outputs/<项目>/成品/style-transfer
```

脚本是**规则迁移**（词表替换 + 句式调整），不是重新创作。
它的强项是**语气一致、不跑题**；弱点是**创意不足** —— 规则改不出的幽默不要假装改出来了。

## 门禁要求

- `compliance`（BLOCK）：风格迁移**禁止**引入极限词与新数据承诺（`最好`/`第一`/`100%` 只能在原文已有的情况下保留）
- `secret_scan`（BLOCK）：正文含密钥即阻断
- `ai_flavor`（WARN）：`funny` 模式若替换后仍是陈述句模板，告警并说明规则能力边界

## 落盘

- 路径：`<项目>/成品/style-transfer/<slug>-<to_style>.md`
- 文件含：`## 改后` / `## 替换明细`（逐条：原文 → 新词）/ `## 风格差异提示`（该风格牺牲了什么）

## 失败处理

| 情况 | 处理 |
|---|---|
| `to_style` 未知 | `ValidationError`，列出全部合法风格 |
| 原文 < 30 字 | 不迁移，回问 |
| 替换后字数变化 > 20% | 记 WARNING，提示语气改动可能已改变信息密度，请人工确认 |
