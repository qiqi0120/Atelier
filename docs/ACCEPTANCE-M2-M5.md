# ACCEPTANCE · M2 收官 ~ M5（2026-10-03）

> 覆盖 `plans/PLAN-M2.md` 收官批 + `specs/SPEC-00` §3 的 M3 / M4 / M5 全部批次。
> 验证方式：pytest（914 通过）· ruff（0 错误）· 前端 vitest（172 通过）+ typecheck + build ·
> `scripts/smoke_m1.py`（26/26）· 真实浏览器 GUI 冒烟（服务 ATELIER_MOCK=1，逐页点验）。
> 提交：eab757f（M2 收官）→ 09f204b（M3）→ 80a0771（M4）→ 452d7be（M5）→ 本批（技能库/能力地图接真数据 + 文档）。

## 1 · M2 收官（SPEC-12：发现域 + 策划 P3）

| 验收标准（SPEC-12 §5） | 结果 |
|---|---|
| RSS 订阅 → 抓取 → 关键词/时间窗过滤去重，重复抓取 inserted=0 | ✅ 37 个 discovery 测试（含假 httpx 响应的解析/过滤/去重/坏 XML/超时） |
| feed 一键转素材池 → 日报 3 段齐全；池空时明确「无可 digest」不编造 | ✅ `fake.requests == []` 断言不调模型；GUI 实测空态文案 |
| 素材存选题库（source=hot 溯源）+ 一键做成内容 | ✅ 前端测试断言请求体 source=hot；做成内容走 fillPrompt 不自动发送 |
| 内容缺口：无订阅信号不调模型；有数据给方向+证据（代码统计） | ✅ insufficient 断言 + keyword_counts 注入 prompt 断言 |
| 算法追踪手工时间线 + 如实标注；UGC 搜索带来源 | ✅ 固定 notice；GUI 实测三 Tab |
| 营销/直播/商单缺段报错不硬编；全部产出过门禁 | ✅ InsightsIncomplete 422 + GateBlocked 422（前端弹层展示改法） |

偏差（SPEC-12 §7）：7 源自动热榜仍无公开数据源，双数据源方案（订阅聚合 + 手工导入）承接，页面固定 notice。

## 2 · M3 制作能力（SPEC-13：37 技能 + visual_qc 门禁）

| 验收标准（SPEC-13 §4） | 结果 |
|---|---|
| 信息图类：粘贴内容 → SVG+HTML 落盘，QC 段如实给检查结果 | ✅ 31 个 m3 测试（quote-card/poster/chart 9 类/mindmap/compare/infographic/meme/电商图冒烟 + qc_svg） |
| 图像四技能真处理（Pillow），参数非法明确报错 | ✅ 放大尺寸断言、压目标 KB 质量二分、圆角 alpha、绿幕抠像换背景像素断言 |
| TTS/ASR 缺钥 409 写明缺哪个；voice-clone/ai-music 如实标 v0 | ✅ required_keys 机制 + GUI 实测「缺少 TTS_API_KEY，运行已禁用」 |
| ffmpeg 技能无 ffmpeg 时明确报安装指引 | ✅ 「未检测到 ffmpeg。brew install ffmpeg…」+ 假 ffmpeg 注入测命令拼装 |
| agent 技能手册可执行、有反问约束 | ✅ loader 校验 + 手册含「反问/不编造」断言 |
| data-report 统计与输入一致（代码算） | ✅ 均值/合计数字断言 |
| 49 技能被 loader 装载，能力地图可见 | ✅ `count==49`；GUI 实测「全部 49 · 制作 45」 |

偏差（SPEC-13 §6）：F-F17 语义分割抠图、F-F9 全量 25+ 图表、GIF 动画、真实节拍检测、PDF 导出——按范围与依赖如实降级并标注。

## 3 · M4 平台扩展（SPEC-14）

| 验收标准（SPEC-14 §3） | 结果 |
|---|---|
| 4 新平台进 `/api/publish/platforms` 与账号中心；B站/视频号须挂视频 | ✅ 18 个 m4 测试（form_rejected / over_limit / 知乎最短 50 字 / 快手免封面） |
| 凭证生命周期：录入（掩码不回传）→ verify → valid；登出 404/200 | ✅ GUI 实测 7 平台卡 + 两条诚实 notice |
| 调度器：到期才跑、dry-run 语义不变、`ATELIER_SCHEDULER=0` 停用；同草稿只触发一次 | ✅ 种数据断言 + records 落库；GUI 实测 Chip「定时发布 · 每 30s 扫描」 |
| 短链：生码 → /s/302 → hits 递增；未知 404 | ✅ + 同目标幂等复用 |
| 优化建议：JSON 契约 + 越界 502 + BLOCK 422 | ✅ publish-optimize- 前缀断言；前端「替换标题」落库 |
| 扫码端点诚实 422 | ✅ 固定 notice（风控边界） |

偏差（SPEC-14 §5）：真实发布与真实扫码仍 dry-run（README 边界不变）；SPEC-06 §2 冻结 3 平台表按只追加扩展为 7。

## 4 · M5 归因与增长（SPEC-15）

| 验收标准 | 结果 |
|---|---|
| 快照/表现/ROI 手工录入（平台数据无公开 API，诚实方案） | ✅ 56 个 attribution 测试；GUI 实测快照录入真实写库且卡内小字即时更新 |
| 增长对比/ROI/看板全部代码计算，AI 不碰数字 | ✅ 最近两快照差值、metrics 聚合断言 |
| 评论洞察/复盘/预测/策略：数据不足不调模型（insufficient + `fake.requests == []`） | ✅ 评论 ≥30 字、复盘 ≥5 条、策略阈值断言 |
| 复盘沉淀回画像：仅在 sediment=true + 画像存在时写 memories（门禁之后） | ✅ |
| 预测固定 notice「参考性质（P3）」 | ✅ score 0-100 越界 502 |
| F-H1 工作台概览：真实 SQL 聚合替代 mock 数字 | ✅ GUI 实测真实 KPI + todo_items + 全零诚实文案 |
| F-H2 数据看板：平台/时间窗切换、insufficient 空态、SVG 折线、Top5 | ✅ GUI 实测「看板只画真实录入的数据」空态（空库正确行为） |
| doctor 第 18 项 local_agents（检测本机 agent CLI，如实说明启用边界） | ✅ |
| `atelier gateway status` 诚实输出（无独立 gateway 进程，start/stop 不适用） | ✅ |

## 5 · 集成修复（最终批）

- **技能库/能力地图接真数据**：两页原为 M1 硬编码目录（20 条、零 API），已重构为消费 `/api/skills`、`/api/capabilities`、`/api/skills/{id}`、运行/轮询/密钥端点——49 技能全部可见，缺钥禁用带原因（F-C10），就地运行含费用确认流（F-C8）与运行历史，能力地图 51 项四分组（F-C4 点击填入不发送）。
- `AuthState` 补机器可读 `state`、账号列表回传 `secret_masked`（前端色标与掩码占位用）。
- `scripts/smoke_m1.py` 断言更新到 49 技能现实（26/26 通过）。

## 6 · 全局回归

| 项 | 结果 |
|---|---|
| 后端 pytest | **914 passed**（会话起点 764 → +150） |
| ruff（line-length 110） | 0 错误 |
| 前端 vitest | **172 passed**（起点 122 → +50）+ tsc 零错误 + vite build 成功 |
| smoke_m1.py | 26/26 |
| GUI 冒烟（真实浏览器） | 工作台/热点/账号/复盘/发布/技能库/能力地图/对话 逐页点验通过；一次真实技能运行端到端成功 |
| schema | v5 → v8（发现域 5 表 / shortlinks / 快照·表现·ROI 3 表），逐版迁移测试覆盖，老数据保留断言通过 |

## 7 · 已知边界（诚实登记，非缺陷）

1. **真实发布与扫码登录仍是 dry-run**——需真实账号与平台风控验证（README「边界」不变）；调度器到点触发的是标准发布流程，发出环节模拟并带 dry_run 标记。
2. 平台表现数据无公开 API：快照/表现/ROI 全部手工录入，看板与 AI 解读只吃真实录入。
3. 声音克隆 / AI 音乐为 v0 准备工具（未接入供应商，页面如实标注）；ffmpeg 依赖的技能在本机无 ffmpeg 时明确报安装指引。
4. 7 源自动热榜、UGC 平台内搜索、算法规则自动追踪：无数据源，页面固定 notice 说明。
5. 短链为本地服务（/s/、hits 本地计数），无公网域。
