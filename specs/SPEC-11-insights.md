# SPEC-11 · 分析域（M2-3a）

| 项 | 值 |
|---|---|
| 版本 | v1.0 |
| 日期 | 2026-10-03 |
| 范围 | PLAN-M2 §2 M2-3 中**不依赖外部数据源**的四个 AI 工具：F-D10 竞品分析 · F-E12 内容策略 · F-E13 账号诊断（诚实模式）· F-E14 受众画像 |
| 明确不含 | F-D5/D7 订阅与 RSS（依赖网络抓取方案，M2-3b 另立 spec）· F-D6 深度加载（平台数据，待方案）· F-D11 内容缺口（依赖 M2-3b 的竞品/订阅数据积累）· F-D12/D13、F-E15/E16/E17（P3，按 PLAN §5 优先砍）· F-H2 数据看板（M5） |
| 依据 | `prd/PRD-Atelier-v1.0.md` §7 F-D10 / §8 F-E12~E14 · `plans/PLAN-M2.md` §2 M2-3 · `specs/SPEC-08` §2（AI 任务模式先例） |

## 0. 已确认决策

| # | 决策 |
|---|---|
| D1 | 四个工具**全部复用** `topics/service` 的 AI 原语：`run_ai_text(domain="insights")` / `extract_json` / `gates_block_or_raise`。session 前缀 `insights-<task>-`，画像走 `TurnRequest.profile` 通道，本域不手工拼画像文本 |
| D2 | **全部不落库、不落产物文件**（与拆解同语义）：分析结果是即席咨询产出，前端展示 + 用户自行取舍；竞品分析出的选题经既有 `POST /topics`（source=manual、source_ref=竞品分析）逐条入库，后端零新端点 |
| D3 | **F-E13 诚实模式（PLAN-M2 硬要求）**：本地 `publish_records` < 5 条 → 返回 `{insufficient: true, stats, need, message}`，**不调模型、不造假分数**。限流信号 / 流量池阶段依赖平台侧数据回收（M5），本批在响应里以固定 `notice` 如实标注「待平台数据回收」 |
| D4 | **诊断的确定性部分由代码持有**：stats（记录数/平台分布/近 30 天/选题流转）由 SQL 聚合，AI 只做解读（findings/advice）——与评分结论同理，不信任模型自算数据 |
| D5 | 输出契约：strategy = Markdown 冻结 4 段（含关键词 `内容支柱` / `受众路径` / `90 天` / `KPI`）；audience / competitor / diagnose = 严格 JSON（§2）。缺段/字段违约 → `InsightsIncomplete`(422，本域定义) / `AIOutputInvalid`(502，复用)，**不新增 errors.py 错误码** |
| D6 | competitor 输入沿用拆解的「拆不动」阈值（≥40 字）；数组字段一律 1..6 条、单项 ≤80 字，越界即 `AIOutputInvalid`，不截断救场 |

## 1. 数据契约

**无新表、schema 不升级**（四工具都是即席产出，D2）。诊断 stats 现场聚合 `publish_records` / `publish_drafts` / `topics` / `artifacts`。

## 2. AI 任务契约（共用路径见 D1）

| 任务 | 输入 | 模型输出约定 | 解析失败 |
|---|---|---|---|
| competitor | text*（≥40 字竞品内容）、profile_id? | JSON `{"topics":[…], "formats":[…], "patterns":[…]}`：竞品在写什么选题、用什么格式、爆款规律；各 1..6 条、单项 2..80 字 | 坏 JSON/字段缺/越界 → 502 |
| strategy | profile_id?（无画像 = 通用建议） | Markdown，4 个 `##` 段名含关键词：内容支柱 / 受众路径 / 90 天 / KPI | 缺段 → `InsightsIncomplete`(422) 列缺段；不硬编补齐 |
| audience | profile_id? | JSON `{"persona":"≤60字", "pains":[…], "scenarios":[…], "preferences":[…], "notes":[…]}`：人群画像一句 + 痛点/场景/内容偏好/避坑各 1..6 条 ≤80 字 | 同 competitor |
| diagnose | profile_id?（stats 由代码注入 prompt） | JSON `{"findings":[{"dimension","status","note"}], "advice":["…"]}`；dimension ∈ 冻结 4 维（垂直度/定位清晰度/更新节奏/平台覆盖）；status ∈ good/warn/bad；findings 4 条、advice 1..5 条 ≤120 字 | 同 competitor；dimension 缺/多/越界 → 502 |

门禁：四工具产出（markdown 或 JSON 序列化文本）过 `compliance + secret_scan + ai_flavor`，BLOCK → `GateBlocked`(422) 带 `gate_items`，整批拒绝。

## 3. API 契约（`api/analytics.py`，按 PLAN-M2 §3 文件归属）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /analytics/competitor | `{text*, profile_id?}` → `{topics, formats, patterns, gate_report}`，不落库 |
| POST | /analytics/strategy | `{profile_id?}` → `{markdown, sections, gate_report}` |
| POST | /analytics/audience | `{profile_id?}` → `{card, gate_report}` |
| POST | /analytics/diagnose | `{profile_id?}` → 记录 <5：`{insufficient: true, stats, need: 5, message}`（**不调模型**）；否则 `{insufficient: false, stats, findings, advice, notice, gate_report}` |

错误体沿用统一形状；本域新错误 `InsightsIncomplete`(422) 定义在 `insights/service.py`（同 SPEC-08 先例，不动 errors.py）。端点全部 async（真 AI 调用）。

## 4. 前端（`web/src/features/analytics/`，占位页转正）

- PageHead（数据复盘 · 主行动 = **账号诊断** primary）+ 四工具卡（图标 + 一句话说明 + 「生成」）：内容策略 / 受众画像 / 竞品分析 / 账号诊断，各自 Modal（topics 域模式，`describeError` 渲染门禁 BLOCK 改法）
- 策略结果用 `react-markdown` 渲染（不挂 rehype-raw，同内容库先例）；受众画像卡渲染为分节卡片；竞品结果三列列表，每条选题附「存入选题库」（调既有 `POST /topics`，source=manual、source_ref=`竞品分析`，成功后 toast 指向选题库）
- 诊断：insufficient → EmptyState「发布 N 条后才有诊断」+ stats 明细 + 去发布中心引导；正常 → findings 列表（good=accent / warn=琥珀 / bad=红，语义色只用于状态）+ 顶部固定 notice「限流信号与流量池阶段需平台数据回收（M5）」
- 画像跟随当前激活画像（同建议弹层）；`api.ts`/`types.ts` 域内自带；零新依赖、零新 CSS 令牌

## 5. 验收标准

1. 粘贴一段竞品内容 → 出选题/格式/爆款规律三列表，且每条选题可一键存入选题库并溯源
2. 一键生成内容策略：四段齐全（支柱/受众路径/90 天/KPI），缺段报错不硬编
3. 受众画像卡：人群一句 + 痛点/场景/偏好/避坑，无画像时出通用版并如实标注
4. 账号诊断：发布记录 <5 条时**明确显示数据不足**而非编造分数；≥5 条时基于本地真实记录给 findings 与建议；限流/流量池维度如实标注依赖 M5
5. 全程无外部数据源依赖；四个工具的产出都过门禁，BLOCK 给改法

## 6. 必测清单（`atelier/tests/test_insights.py`）

- competitor：<40 字 → 422 不调模型；JSON 齐 → 200 三列表形状与条数边界；BLOCK 词 → 422 带 gate_items；坏 JSON/数组越界 → 502；画像注入 + session 前缀 `insights-competitor-`
- strategy：4 段齐 → sections 全 true；缺段 → 422 `InsightsIncomplete` 列缺段；无画像 → 通用模式 prompt 断言
- audience：JSON → 200 卡片形状；persona 缺 → 502；数组越界 → 502
- diagnose：<5 条记录 → `insufficient: true` 且 **fake.requests 为空**（不调模型）；造 5 条记录 → `insufficient: false`、stats 与库内一致（平台分布/近 30 天）、prompt 里含 stats 摘要；dimension 越界 → 502；BLOCK → 422
- 回归：schema version 不变（无新表）

`web/src/features/analytics/__tests__/analytics.test.tsx`：四工具卡渲染；诊断 insufficient 空态文案；诊断结果 findings 状态色与 notice；竞品三列表 + 存入选题库请求体（source/source_ref）；策略 markdown 渲染；BLOCK 弹层内改法展示。

## 7. 偏差与待办登记

- PLAN-M2 §2 M2-3 预估后端 `discovery/**` + `api/{discovery,analytics}.py`——本批只建 `atelier/server/insights/**` + `api/analytics.py`；`discovery/**` 留给 M2-3b（订阅/RSS），命名偏差随批登记
- PLAN-M2 M2-3 出口标准 #1（RSS 过滤去重）与 #3（内容缺口）依赖 M2-3b，随 F-D8 数据源决策一起排；#2（竞品拆解）#4（诊断诚实模式）由本批闭合
- PRD F-E13 的「限流信号/流量池阶段」需要平台侧数据（M5 回收），本批固定 notice 如实标注，不做假诊断（PLAN §2 ⚠️ 不做假数据铁律）
- 竞品选题入库走既有 POST /topics（source=manual）；`hot` 来源仍留给热点域（M2-3b/后续）
