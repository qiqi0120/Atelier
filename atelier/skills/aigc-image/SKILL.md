---
id: aigc-image
name: AI 生图
layer: 制作
maturity: v2
trigger: 当你说「生张图」「AI 画一张」「给我配图」「文生图」时使用
cost: 按量计费 · 需密钥
required_keys: [MINIMAX_API_KEY]
params:
  - {key: prompt, label: 画面描述, default: ""}
  - {key: count, label: 张数, default: "1"}
  - {key: ratio, label: 比例, default: "3:4"}
  - {key: style, label: 风格, default: ""}
  - {key: ref_image, label: 参考图路径, default: ""}
outputs: [image]
paid: true
---

# AI 生图

文生图 / 图生图 / 变体，产出可直接进卡片或视频的配图。

> ⚠️ **v2 · 需配置 + 按量计费**。未配置 `MINIMAX_API_KEY` 时**运行按钮禁用**，
> 接口返回 `409 SkillMissingKey`。配图类技能是 `xhs-card` 的**可选补充**：
> 用户只要排版卡片时不要强行引导过来花钱。

## 前置门禁

1. **密钥**：`MINIMAX_API_KEY`
2. **费用确认**：`paid: true` → 先返回费用预估，`confirm_cost: true` 才执行
3. **prompt** ≥ 8 字，且**不含真实人名/明星/品牌 logo**（肖像与商标风险）
4. `ratio` 白名单：`1:1` `3:4` `4:3` `9:16` `16:9`，其它值 `ValidationError`

## 画面描述怎么写

| 要素 | 例子 |
|---|---|
| 主体 | 「一只橘猫」 |
| 场景 | 「木质书桌上，旁边摊着笔记本」 |
| 光线 | 「午后侧光，暖调」 |
| 镜头 | 「俯拍 50mm，浅景深」 |
| 排除 | `--no text, --no watermark` |

**不要**在 prompt 里写「在图片上加文字」—— 生图模型写不对中文，文字一律用
`xhs-card` 叠加。

## 产出

- 路径：`<项目>/成品/aigc-image/`
- 文件名带序号与随机后缀：`img-01-a3f9c2.png`（同 prompt 两次运行不覆盖旧图）
- 响应里回传**真实落盘路径**，不要只回传 base64

## 失败处理

| 情况 | 处理 |
|---|---|
| 缺密钥 | `SkillMissingKey`（409），写明缺 `MINIMAX_API_KEY` |
| 内容审核拒绝 | 如实转述审核原因，**不要重试到通过为止**（反复重试既烧钱也可能绕过审核） |
| 供应商超时 | 报超时 + 未计费确认，不产出空文件 |
| `count` > 4 | `ValidationError`，一次最多 4 张 |
