---
id: social-copy
name: 通用社媒文案
layer: 制作
maturity: v0
trigger: 当你说「写个小红书」「发微博」「写条知乎」「出个 B 站标题」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: topic, label: 主题 / 素材, default: ""}
  - {key: platform, label: 平台, default: "all"}
  - {key: tone, label: 语气, default: "friend"}
  - {key: keypoints, label: 必带信息点, default: ""}
outputs: [markdown]
paid: false
---

# 通用社媒文案

一份母版 → 五种平台形态：小红书 / 微博 / 知乎 / 公众号 / B站。
不是简单改字数，**每个平台的体裁和语气不同**。

| platform | 标题上限 | 体裁要点 |
|---|---|---|
| `xhs` 小红书 | 20 字 | 短句分段、emoji 做分隔符、结尾 5–10 个标签 |
| `weibo` 微博 | 140 字 | 单段、话题用 `#xx#`、前 15 字决定点击 |
| `zhihu` 知乎 | 50 字 | 结论前置、给依据、可加「利益相关」声明 |
| `gzh` 公众号 | 30 字 | 导语 + 小标题分段、结尾引导（点赞/在看/转发） |
| `bili` B站 | 80 字 | 标题带信息量或反差、简介 3 行内、标签 10 个 |

## 执行

```bash
python atelier/skills/social-copy/run.py \
  --params '{"topic":"…","platform":"all","keypoints":"预算 300 元, 3 天上手"}' \
  --out outputs/<项目>/成品/social-copy
```

脚本从 `topic` + `keypoints` 生成**结构化骨架**（标题候选 / 分段 / 标签 / 平台适配），
**不是**让模型凭空造内容。写正文由 agent 承接：脚本给体裁约束，agent 填血肉。

## 门禁要求

逐平台跑：
- `wordcount`（BLOCK）：各平台按上表上限判超限
- `compliance`（BLOCK）：极限词/医疗功效词
- `secret_scan`（BLOCK）：含密钥即阻断
- `ai_flavor`（WARN）：模板腔告警

## 落盘

- 路径：`<项目>/成品/social-copy/<slug>-<platform>.md`，`platform=all` 时一个文件含五段
- 每段含：标题 / 正文 / 标签 / 字数 / 平台专属提示（如微博的话题串）

## 失败处理

| 情况 | 处理 |
|---|---|
| `topic` 少于 10 字 | 不猜，回问要写什么 |
| `keypoints` 与 `topic` 冲突 | 抛 `ValidationError` 并指出冲突点，让人裁决 |
| 某平台字数装不下 | 触发 `crop` 技能裁剪，不许硬塞 |
