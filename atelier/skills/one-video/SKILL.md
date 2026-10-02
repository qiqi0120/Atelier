---
id: one-video
name: 一键成片
layer: 制作
maturity: v2
trigger: 当你说「一键成片」「把这段文案做成视频」「做成竖版短视频」时使用
cost: 按量计费 · 需密钥
required_keys: [MINIMAX_API_KEY]
params:
  - {key: topic, label: 主题, default: ""}
  - {key: duration, label: 时长（秒）, default: "45"}
  - {key: ratio, label: 画幅, default: "9:16"}
  - {key: style, label: 口播风格, default: "friend"}
outputs: [video]
paid: true
---

# 一键成片

主题 → 文案 → 配图/AI 视频 → 配音 → 字幕 → BGM → 合成，产出可直接发的竖版视频。

> ⚠️ **v2 · 需配置 + 按量计费**。未配置 `MINIMAX_API_KEY` 时**运行按钮禁用**，
> 接口返回 `409 SkillMissingKey`，message 写明缺哪个密钥。**不要试图绕过**。

## 前置门禁（不通过就不要花钱）

1. **密钥**：`MINIMAX_API_KEY` 已配置（前端只显示掩码 `sk-****3f7a`）
2. **费用确认**：`paid: true` → 第一次点击运行**只返回费用预估**，
   必须 `POST /api/skills/one-video/run {"confirm_cost": true}` 才真跑（PRD 原则三）
3. **主题**：`topic` ≥ 8 字，否则回问，不要瞎编内容
4. **合规**：文案先过 `compliance` + `secret_scan`，**先过门禁再花钱**

## 费用预估怎么报

```
本次预计消耗：
  视频生成  45s × ¥0.5/秒   ≈ ¥22.50
  配音      45s × ¥0.02/秒  ≈ ¥0.90
  合计      ≈ ¥23.40
确认后才开始计费。点「取消」不产生任何费用。
```

**估算是保守上界**，实际按生成秒数结算。跑完把 `cost_actual` 一并返回，不许只报预估。

## 执行

```bash
# 单步：先出文案（不花钱），用户确认后再花钱合成
python atelier/skills/one-video/script.py --params '{"topic":"…","duration":45}' --out …
```

合成走 `atelier_skill_run` / 平台适配层，**不要在 SKILL.md 里硬编码厂商 SDK 调用**：
厂商协议会变，接口不变。

## 产出

- 路径：`<项目>/成品/one-video/`
- `script.md`（文案，可单独改）/ `voice.wav` / `subs.srt` / `final_9x16.mp4`
- 合成用 FFmpeg；**FFmpeg 缺失 → 明确报「缺 FFmpeg，无法合成」**，不要交半成品

## 失败处理

| 情况 | 处理 |
|---|---|
| 缺密钥 | `SkillMissingKey`（409），说明去「设置 / 技能卡 API 配置」填 |
| 未确认费用 | 返回费用预估，`status: cost_pending`，**不执行** |
| 供应商 5xx | 报供应商错误码原文 + 已产生的费用，**部分完成也要落盘已产物** |
| 生成中断 | 保留已完成片段，允许续跑；不许留下 0 字节 mp4 |
