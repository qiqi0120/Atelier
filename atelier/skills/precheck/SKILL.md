---
id: precheck
name: 发布前预检
layer: 发布
maturity: v0
trigger: 当你说「发之前检查一下」「能发吗」「帮我预检」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: title, label: 标题, default: ""}
  - {key: body, label: 正文, default: ""}
  - {key: platform, label: 平台, default: "xhs"}
  - {key: hashtags, label: 话题, default: ""}
outputs: [markdown]
paid: false
---

# 发布前预检

发之前把能挡下来的问题都挡住。**预检不发布** —— 只回答「能不能发」，
实际发布走发布中心（`POST /api/publish/...`）。

## 检查项（本技能确定性执行）

| # | 项 | 分级 | 判定 |
|---|---|---|---|
| 1 | 标题非空 | BLOCK | 空标题直接拦 |
| 2 | 正文字数 ≤ 平台上限 | BLOCK | xhs 1000 / dy 55 / gzh 20000 |
| 3 | 极限词 / 医疗功效 | BLOCK | 命中即拦 |
| 4 | 违禁品词 | BLOCK | 命中即拦 |
| 5 | 密钥泄漏 | BLOCK | fail-closed：扫描器异常按命中处理 |
| 6 | 话题标签数量 | WARN | xhs 建议 5–10 个 |
| 7 | 开头是否铺垫过长 | WARN | 前 40 字没给结论则告警 |
| 8 | AI 味五维 | WARN | 低于阈值告警 |

## 执行

```bash
python atelier/skills/precheck/run.py \
  --params '{"title":"…","body":"…","platform":"xhs","hashtags":"a,b,c"}' \
  --out outputs/<项目>/成品/precheck
```

脚本**内建词表做 1–5 项的确定性判定**（不依赖 gates 模块是否就绪），
WARN 项按启发式打分。有门禁框架时（`gates.registry.run_gates`），agent 应额外跑一次官方门禁并以官方结果为准。

## 门禁要求

本技能自身**就是**门禁的执行者，输出必须包含每项的 `severity` / `passed` / `message` / `fix_hint`。
出现任一 BLOCK 未通过 → 结论必须是 `❌ 不可发布`，并给出修法。

## 落盘

- 路径：`<项目>/成品/precheck/<slug>.md`
- 结构：`## 结论` / `## 逐项结果`（表格）/ `## 修法`（只给可执行动作）

## 失败处理

| 情况 | 处理 |
|---|---|
| 平台未知 | `ValidationError`，列出三平台 |
| body 为空 | 拦（BLOCK），不要给「通过」 |
| 词表扫描器自身报错 | **按命中处理**（fail-closed），并在产物里写明扫描器异常 |
