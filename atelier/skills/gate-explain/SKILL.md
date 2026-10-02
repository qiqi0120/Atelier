---
id: gate-explain
name: 门禁说明
layer: 通用
maturity: v0
trigger: 当你说「为什么要拦我」「这个门禁是什么」「BLOCK 和 WARN 有什么区别」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: gate_id, label: 门禁 id, default: ""}
  - {key: why, label: 想解决的问题, default: ""}
outputs: [markdown]
paid: false
---

# 门禁说明

解释「为什么这条被拦」。门禁是**代码路径上的事实**，不是提示词约定（SPEC-00 §1.1 ①）。

## BLOCK vs WARN

| 分级 | 行为 | 含义 |
|---|---|---|
| `BLOCK` | 产物**不许**落盘，发布**不许**继续 | 违反平台硬规则或安全红线 |
| `WARN` | 只告警，**可以**继续 | 质量建议，模型有权坚持自己的判断 |

WARN 被打回时**不要**无脑照改：先说清代价，用户认为值得再改（PRD 原则二）。

## 内置门禁

| id | 分级 | 检查什么 | 怎么修 |
|---|---|---|---|
| `wordcount` | BLOCK | 各平台字数上限 | `crop` 技能裁剪 |
| `compliance` | BLOCK | 极限词 / 医疗功效 / 违禁品词 | 换表述，不要绕词 |
| `secret_scan` | BLOCK | 出站内容里的 API key / token / 私钥 | 从正文删掉 |
| `ai_flavor` | WARN | AI 味五维（直接性/节奏/信任度/活人感/精炼度） | `de-ai` 技能 |

## 遇到 `GateBlocked` 怎么办

1. **看 `detail.gate_items`**，里面是逐项结果（`gate` / `actual` / `limit` / `message` / `fix_hint`）
2. **按 `fix_hint` 改**，不要改门禁阈值 —— 用户看不到门禁阈值，但会被结果挡住
3. 改完**重跑**门禁，别口头声称过了
4. 门禁真的误伤了（如「第一」出现在引用他人原话里）→ 如实告诉用户是哪一条、为什么是 BLOCK，
   让用户决定是否手动放行。**agent 不得自行放宽门禁**

## `secret_scan` 为什么是 fail-closed

扫描器自身抛异常时**按命中处理**（视为不通过）。理由：静默放行等于没有这道门。
遇到这种情况要**明确告诉用户「扫描器异常，本次按不通过处理」**，不要装作正常。

## 输出

直接用表格解释 + 一条可执行的下一步。**不产出文件**，这是问答型技能：
除非用户明确说「写份说明文档」，否则只在对话里回答。
