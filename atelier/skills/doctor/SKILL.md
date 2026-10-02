---
id: doctor
name: 环境体检
layer: 通用
maturity: v0
trigger: 当你说「体检」「环境有问题吗」「 doctor 」「为什么跑不起来」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: verbose, label: 详细输出, default: "false"}
outputs: [markdown]
paid: false
---

# 环境体检

回答「我的 Atelier 现在能不能干活」。**只诊断，不修** —— 修复动作要人确认。

## 委托给 doctor 模块

本技能是**说明型技能**，实际检查由地基的 doctor 模块执行（`atelier server doctor` / `doctor` 技能域）。
不要自己重新实现一套检查 —— 两套检查会给出矛盾结论。

## 体检项（与 SPEC-00 M0「doctor 17 项」对应）

| 组 | 检查 |
|---|---|
| Python | 解释器版本 ≥ 3.10、关键依赖（fastapi/pydantic/pyyaml/cryptography）可导入 |
| 目录 | `outputs/` `profiles/` `var/` 存在且可写 |
| 路径 | ROOT 可解析、`resolve_inside` 能挡住 `..` 与 symlink 逃逸 |
| Harness | provider 可用、`ANTHROPIC_API_KEY` 已配置（未配置 → 只影响 AI 产出，不影响本地技能） |
| 门禁 | 4 个内置门禁已注册、可执行 |
| 技能 | 技能库可加载、能力地图无死链 |
| 密钥 | keychain 或 `var/secrets.enc` 可用 |
| 外部 | FFmpeg（视频类技能）、Node/pnpm（前端构建） |

## 结果解读

每项三态：`✅ 通过` / `⚠️ 降级`（有替代路径）/ `❌ 阻断`（相关功能不可用）。
**只报阻断项 + 与用户诉求相关的项**，不要把 17 项全糊在脸上。

| 用户在做什么 | 优先看 |
|---|---|
| 写文案、排版 | 目录可写 + 门禁可用 |
| 跑一键成片 | 密钥 + FFmpeg |
| 启动 Web | Node/pnpm + 前端 dist |

## 失败处理

| 情况 | 处理 |
|---|---|
| 某项检查自身抛异常 | **如实报该项「检查失败：<异常>」**，不许当成通过（PRD 原则四） |
| 缺可选依赖（如 Pillow） | 报「⚠️ 降级」并说明影响范围（例：知识卡输出 SVG 而非 PNG） |
| 缺必需依赖 | 报「❌ 阻断」并给安装命令 |
