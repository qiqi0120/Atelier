---
id: xhs-card
name: 小红书知识卡
layer: 制作
maturity: v0
trigger: 当你说「做成小红书图文」「做知识卡」「1080×1440 卡片」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: title, label: 卡片标题, default: ""}
  - {key: body, label: 正文素材, default: ""}
  - {key: count, label: 张数, default: "3"}
  - {key: size, label: 尺寸, default: "1080×1440"}
  - {key: theme, label: 配色, default: "warm"}
  - {key: cta, label: 行动号召, default: "收藏起来慢慢看"}
outputs: [image]
paid: false
---

# 小红书知识卡

把一段文字拆成 N 张竖版知识卡（默认 3 张 1080×1440），产出可直接发小红书的图。

## 何时用

用户给了一段想「做成图文」的内容，且内容天然可切成 2–6 个并列知识点。
不适合：内容本身是连续论述（应改用 `wechat-layout`），或需要真实照片配图（用 `aigc-image`）。

## 执行

本技能带确定性脚本，**优先跑脚本，不要手搓版式**：

```bash
python atelier/skills/xhs-card/run.py \
  --params '{"title":"…","body":"…","count":3,"theme":"warm"}' \
  --out outputs/<项目>/成品/xhs-card
```

脚本行为：

| 输入 | 行为 |
|---|---|
| `count` | 按段落/句号切分成 N 段；段落多于 N 时合并尾部，段落不足 N 时按句号二次切分 |
| `theme` | `warm`（暖米色）/ `cool`（冷灰蓝）/ `ink`（黑白高对比），只改配色不改字号 |
| `size` | 默认 1080×1440；只接受 `宽×高` 形式 |

## 输出格式（重要）

- **有 Pillow 时**产出 `<n>-<slug>.png`（真实位图）
- **无 Pillow 时**产出 `<n>-<slug>.svg`（矢量，中文渲染无损，任何浏览器/设计工具可打开）

> 当前运行环境未安装 Pillow，因此实际产出为 **SVG**。这是有意为之的降级，不是缺陷：
> 矢量图缩放不糊、可二次排版，但小红书 直接上传要求图片格式，发布前需另存为 PNG。
> 装上 Pillow（`pip install pillow`）后重跑即自动切到 PNG，脚本无需改动。

无论哪条路径都会额外产出 `preview.html`，双击即可逐张查看。

## 版式规范（脚本已内置，AI 不要另定）

- 边距 72px，正文安全区 936px
- 标题 84px 粗，最多 2 行；正文 52px，行高 1.6
- 每张卡底部固定：左下角页码 `01/03`，右下角 CTA
- 文字颜色与背景对比度 ≥ 4.5:1，死白/死黑不许铺满全图

## 门禁要求

落盘前必须调 `atelier_gate_run`：

- `compliance`：BLOCK。卡片文案里出现极限词（最/第一/根治/国家级）→ **必须改文案，不许改门禁**
- `secret_scan`：BLOCK。素材里混进 API key / 手机号 → 阻断
- `ai_flavor`：WARN。标题若是「揭秘」「必看」「99% 的人不知道」这类模板腔 → 软告警，可保留但要知情

## 落盘

- 路径：`<项目>/成品/xhs-card/`
- 必须在响应里给出 `preview.html` 的可点击路径，让用户先看再发
- 不要替用户发布

## 失败处理

| 情况 | 处理 |
|---|---|
| `body` 为空 | 不猜内容，回问用户要素材 |
| `count` 非法（非 1–9 整数） | 抛 `ValidationError`，说清合法区间 |
| Pillow 存在但渲染失败 | 记 WARNING，自动回落 SVG，不要静默丢图 |
