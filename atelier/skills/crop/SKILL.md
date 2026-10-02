---
id: crop
name: 字数裁剪 / 摘要 / 金句
layer: 制作
maturity: v0
trigger: 当你说「超字数了」「裁一下」「提取金句」「太长了」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: text, label: 原文, default: ""}
  - {key: mode, label: 模式, default: "crop"}
  - {key: limit, label: 目标字数, default: "1000"}
  - {key: platform, label: 平台, default: "xhs"}
  - {key: keep_title, label: 保留标题, default: "true"}
outputs: [markdown]
paid: false
---

# 字数裁剪 / 摘要 / 金句提取

三模式解决「超字数」和「太长」两类问题，且**永不丢事实**。

| mode | 用途 | 行为 |
|---|---|---|
| `crop` | 超平台上限 | 按句号边界硬裁到 `limit` 内，**不重写** |
| `summary` | 只想看短的 | 抽取式摘要：按句子信息密度排序取 top-N，保留原句 |
| `golden` | 要能传播的句子 | 提取金句：短句 + 有数字/对比/断言 → 打分取 top-N |

## 平台字数上限（内置）

| 平台 | 上限 |
|---|---|
| `xhs` 小红书正文 | 1000 |
| `dy` 抖音标题 | 55 |
| `gzh` 公众号 | 20000 |
| `zhihu` 知乎 | 20000 |

与 `gates/wordcount.py` 同源；上限不同以门禁为准，本技能只做建议值。

## 执行

```bash
python atelier/skills/crop/run.py \
  --params '{"text":"…","mode":"crop","limit":900,"platform":"xhs"}' \
  --out outputs/<项目>/成品/crop
```

`crop` 模式保证不切断句子：若最后一句放不下，回退到上一完整句并**明确告知实际字数**
（不要假装刚好卡线，也不要截半句）。

## 门禁要求

- `wordcount`（BLOCK）：裁完**必须**重跑一次确认 ≤ 上限；仍超限说明裁剪失败，不许交付
- `compliance`（BLOCK）：裁剪只减不增，**禁止**为了凑字数补写新句子
- `ai_flavor`（WARN）：`summary` 模式若输出全是长句套话，软告警

## 落盘

- 路径：`<项目>/成品/crop/<slug>-<mode>.md`
- 文件含：`## 裁剪结果`（正文）/ `## 字数`（原 N 字 → 现 M 字，limit K）/ `## 裁掉的部分`（原文可见，便于回溯）

## 失败处理

| 情况 | 处理 |
|---|---|
| 原文已 ≤ limit | 原样返回并说明「无需裁剪」，不假装做了工作 |
| `crop` 无法在不超限下保住完整句 | 回退到上一句 + 说明差几字，让人决定 |
| `keep_facts=true` 下丢数字 | 视为失败，回滚并提示 |
