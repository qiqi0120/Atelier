# SPEC-15 · 归因与增长闭环（M5，仅后端）

| 项 | 值 |
|---|---|
| 版本 | v1.0 |
| 日期 | 2026-10-03 |
| 范围 | F-G30 增长对比 · F-G31 内容表现回收 · F-G32 评论洞察 · F-G33 内容复盘 · F-G34 ROI 核算 · F-G35 爆款预测（P3）· F-G36 策略建议 · F-H1/F-H2 的后端数据源（workbench-summary / dashboard）· F-I5 本地 Agent 检测（doctor 增项）· F-J6 gateway CLI |
| 明确不含 | 平台表现数据**自动抓取**（各平台均无公开数据 API，诚实不做）· F-H1/F-H2 前端改造（本批只交付数据源端点，前端另批）· F-I5 的「启用外部 agent」（本批只检测；启用属 harness registry 扩展）· F-J6 的 `gateway start/stop`（本仓库 harness 是进程内直连，无独立网关进程，如实不做）· AI 产出落库（复盘/洞察/建议均不落库，只有用户手工录入的结构化数据进库） |
| 依据 | `specs/SPEC-00-overview.md` §3 M5 · `prd/PRD-Atelier-v1.0.md` §7（F-G30~G36 / F-H1~H2 / F-I5 / F-J6）· `specs/SPEC-11`（AI 任务与诚实模式先例）· `specs/SPEC-12`（insufficient 语义与「无数据源就手工录入」先例） |

## 0. 已确认决策

| # | 决策 |
|---|---|
| D1 | **诚实原则是本域硬约束**：平台侧表现数据不可自动抓取（无公开 API），全部由用户手工录入快照 / 粘贴表现数据与评论；**AI 只解读代码算出的统计，绝不编数**。数据不足的端点返回 ``{insufficient: true, need, message}`` 且**不调模型**（``fake.requests == []`` 可测），与 SPEC-11 §0 D3 / SPEC-12 D3 同语义 |
| D2 | schema v8 只追加 3 张表：``account_snapshots``（账号快照，手工定期抄录）/ ``content_metrics``（单条内容表现，引用 ``publish_records.id``，删记录级联删指标）/ ``roi_entries``（投入台账，record_id 可空、不设外键——投入可先于发布记录存在）。``TABLE_NAMES`` / ``_EXPECTED`` / ``_MIGRATIONS`` 同步追加，``SCHEMA_VERSION = 8``，不动既有行 |
| D3 | AI 任务（评论洞察 / 复盘 / 预测 / 策略）复用 ``topics.service`` 原语（``run_ai_text(domain="attribution")`` / ``extract_json`` / ``gates_block_or_raise`` / ``AIOutputInvalid``），session 前缀 ``attribution-<task>-``；产出先过 ``compliance + secret_scan + ai_flavor`` 门禁，BLOCK 即 ``GateBlocked``(422) 附逐项改法 |
| D4 | 域内新错误只有一个：``AttributionIncomplete``（AI Markdown 缺段，422），定义在 ``attribution/service.py``，不动 ``errors.py``（同 SPEC-11/12 先例）；模型输出违约沿用 ``AIOutputInvalid``(502) |
| D5 | F-G33 复盘的「沉淀进画像」走 ``profile.store.add_memory(profile_id, text, source="复盘沉淀")``（``INSERT INTO memories`` 的既有唯一出口），**仅当**请求同时带 ``profile_id`` 且 ``sediment: true``（默认 false）才写；沉淀文本取「下一步」段之前的要点，截断到 500 字；无画像时返回通用复盘并如实标注（响应带 ``profile_used: false``） |
| D6 | F-G35 爆款预测是 P3 参考性质：响应**必须**带固定 ``notice``「预测是参考性质（P3），基于文本特征与通用经验，不保证实际表现」；``score`` 非 0-100 整数 → 502；``verdict`` 只允许 试试/改后发/放弃 |
| D7 | F-G30 增长对比 = 该平台**最近两条快照的差值**，代码相减，不调模型；不足两条 → ``{insufficient: true, need: 2, message}``。F-H2 dashboard 无快照且无 metrics → ``insufficient: true + message``，前端渲染空态 |
| D8 | doctor 增第 18 项 ``local_agents``：``shutil.which`` 探测本机 agent CLI（claude/codex/gemini/aider/cursor-agent），检测到与否都是合法状态（一律 pass），hint 固定说明「启用外部 agent 属 harness registry 扩展」。``DOCTOR_CHECK_COUNT`` 17 → 18；SPEC-00 §3 的「17 项」数字偏差登记 §6。``gateway`` 子命令只做 ``status``（读 harness registry 配置判定 + 密钥掩码 + 固定诚实说明）；``start/stop`` 不做并在 help text 说明原因 |

## 1. 数据契约（schema v8）

| 表 | 列 | 说明 |
|---|---|---|
| `account_snapshots` | id TEXT PK, platform* NOT NULL, captured_at* NOT NULL(YYYY-MM-DD 零填充), followers INT 默认0, likes_total INT 默认0, works_total INT 默认0, note, created_at, updated_at | 账号整体快照；用户隔段时间手工抄一次（创作中心首页数字）。增长对比取同 platform 最近两条 |
| `content_metrics` | id TEXT PK, record_id* NOT NULL REFERENCES publish_records(id) ON DELETE CASCADE, platform* NOT NULL, views/likes/comments/shares INT 默认0, collected_at* NOT NULL(YYYY-MM-DD), note, created_at, updated_at | 单条内容表现；platform 必须与 record 一致（服务层校验，不一致 422）；一条记录可多次回收（时间序列） |
| `roi_entries` | id TEXT PK, record_id(可空，无外键——投入可先于发布存在), project, hours REAL 默认0, amount REAL 默认0, note, created_at | 投入台账（写稿时长 / 采购金额等）；hours/amount ≥ 0 服务层校验 |

索引：`idx_snapshots_platform ON account_snapshots(platform, captured_at)`、`idx_metrics_record ON content_metrics(record_id, collected_at)`、`idx_roi_created ON roi_entries(created_at)`。

## 2. 服务与 API 契约

后端新目录 `atelier/server/attribution/`（`service.py`：CRUD + 聚合 + 域错误 + `sediment_memory`；`insights.py`：四个 AI 任务）+ `api/attribution.py`。CRUD 端点同步 def、AI 端点 async；字面路由声明在 `/{id}` 之前；不改 `main.py`（`_autoload_routers` 自动挂载）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/attribution/snapshots` | 列表（`platform?` 过滤，captured_at 倒序）/ 录入（201；platform 必填 ≤40 字；captured_at 零填充 YYYY-MM-DD 校验，复用 discovery 的 `validate_iso_date` 口径） |
| DELETE | `/attribution/snapshots/{id}` | 删（不存在 404） |
| GET | `/attribution/growth?platform=&days=` | **F-G30（代码算，不调模型）**：platform 必填；取该平台最近两条快照，返回 `{current, previous, delta{followers,likes_total,works_total}, window_days}`；`days>0` 时只看窗口内快照；不足两条 → `{insufficient: true, need: 2, message}` |
| POST | `/attribution/metrics` | **F-G31**（201）：`record_id*` 必须存在于 publish_records（404）、`platform*` 与该 record 一致（422）、四项计数 ≥ 0 |
| GET | `/attribution/metrics?platform=&days=` | 列表（collected_at 倒序）+ 代码聚合 `{items, total, agg{total_views, total_likes, total_comments, total_shares, avg_views}}` |
| POST | `/attribution/roi` | **F-G34**（201）：`hours/amount` 为数字且 ≥ 0，至少一项 > 0；record_id/project/note 可选 |
| GET | `/attribution/roi/summary?days=` | **代码算**：窗口内投入合计（hours/amount）+ 同期 content_metrics 产出合计 → `{total_hours, total_amount, content_count, output{total_views,total_likes,total_comments,total_shares}, roi_hint}`；roi_entries 为 0 → `{insufficient: true, need: 1, message}` 不编 ROI |
| POST | `/attribution/comments-insight` | **F-G32（AI）**：`{text*, profile_id?}`；`text` < 30 字 → 422 **不调模型**；要求严格 JSON `{"themes":[{"theme","count_hint","sample_quote"}], "requests":[...], "sentiment":{"positive","negative","neutral"}}`；themes 1..6 条、theme/sample_quote ≤80 字、count_hint ≤20 字且 prompt 声明它是「用户粘贴内容里的近似计数，AI 不得虚构精确数字」（越界 502）→ 门禁 → 不落库 |
| POST | `/attribution/review` | **F-G33（AI，诚实模式）**：stats（publish_records 条数/平台分布 + content_metrics 聚合 + topics 流转）**代码算**；`stats.records_total < 5` → `{insufficient: true, need: 5, message, stats}` 不调模型；否则 stats JSON 注入 prompt（「只解读不编数字」）→ Markdown 恰 4 段（`有效结构` / `受众偏好` / `失效做法` / `下一步`），缺段 422 `AttributionIncomplete` → 门禁 → `sediment: true` 且带 `profile_id` 时把「下一步」之前的要点写进画像长期记忆（返回 `{sedimented: true, memory_id}`），否则不写；无画像 → 通用复盘 + `profile_used: false` |
| POST | `/attribution/predict` | **F-G35（AI，P3）**：`{title*, body*, platform*, profile_id?}` → 严格 JSON `{"score": 0-100整数, "factors":[{"name","impact"}](1..5), "verdict": "试试|改后发|放弃"}`；score 非 0-100 / verdict 越界 / factors 越界 → 502；响应固定 `notice`（D6）→ 门禁 → 不落库 |
| POST | `/attribution/strategy` | **F-G36（AI，诚实模式）**：无任何 content_metrics 且 publish_records < 3 → `{insufficient: true, need: 3, message}` 不调模型；否则代码聚合历史（表现最佳平台 / 平均互动 / 题材分布）注入 prompt → Markdown 恰 3 段（`保持` / `调整` / `停止`），缺段 422 → 门禁 → 不落库 |
| GET | `/attribution/workbench-summary` | **F-H1 数据源（只读，SQL 现查，无写死数字）**：`{topics{todo,doing,done}, drafts_pending(有 scheduled_date 且无 sent 记录), calendar_today(今日事件数), hot_pending, artifacts_last_7d, records_last_7d{sent,failed}, scheduler(直接 import publish.scheduler.get_status())}` |
| GET | `/attribution/dashboard?platform=&days=30` | **F-H2 数据源（只读）**：`{snapshots:[{captured_at, followers}升序], metrics_by_day:[{collected_at, views, likes, comments, shares}], top_contents:[{title, platform, views, likes} 前5], insufficient, message?}`；快照/metrics 按 platform 过滤；无快照且无 metrics → `insufficient: true` + message |

## 3. CLI 与 doctor

| 项 | 契约 |
|---|---|
| doctor 第 18 项 `local_agents` | `shutil.which` 依次探测 `claude` / `codex` / `gemini` / `aider` / `cursor-agent`；value 列出检测到的（如 `claude, codex`）或「未检测到本机 agent CLI」；status 一律 pass（检测到与否都是合法状态）；hint 固定「启用外部 agent 属 harness registry 扩展，当前仅支持 claude-agent-sdk / Mock」。`DOCTOR_CHECK_COUNT = 18`，`CHECKS` 末尾追加 |
| `atelier gateway status`（`--json`） | 诚实实现：本仓库 harness 是**进程内直连**（claude-agent-sdk / Mock），没有独立 gateway 守护进程。输出：`harness`（ATELIER_MOCK=1 → mock；有 ANTHROPIC_API_KEY → claude-sdk；两者皆无 → 未配置）、`health`（CLI 环境只报配置判定，注明真实 health 见 `atelier web` 后的 /api/health）、密钥掩码（`config.redacted()` 口径）、固定一行「本仓库无独立 gateway 进程；start/stop 不适用，进程随 `atelier web` 生命周期」。`gateway start` / `gateway stop` **不做**：输出不适用原因并返回非零 |
| `atelier doctor` 文案 | 模块 docstring 与 `--help` 的「17 项」同步改 18 项 |

## 4. 前端（不在本批）

F-H1/F-H2/F-G30~G36 的页面与组件改造由后续前端批交付；本批 `web/` 零改动，`workbench-summary` / `dashboard` 两端点即为届时替代 mock 数字的契约（形状见 §2，insufficient 语义见 D7）。

## 5. 验收标准

1. 手工录入两条同平台快照 → growth 返回两项差值与 window_days；只有一条时诚实 insufficient 且不调模型
2. metrics 录入校验 record 存在性与 platform 一致性（404 / 422）；列表聚合数字与库内一致
3. ROI：hours/amount 负数 422；无投入记录 summary 诚实 insufficient；有投入时 roi_hint 只复述代码算出的数字
4. 评论洞察 <30 字 422 不调模型；正常输出 themes 1..6 条且 count_hint 标注近似；越界 502；BLOCK 422 附改法
5. 复盘：记录 <5 条诚实 insufficient；≥5 条时 prompt 注入本地 stats；缺段 422 `AttributionIncomplete`；sediment=true + profile_id 时 memories 表多一条（source=复盘沉淀），且写库动作在门禁之后
6. 预测响应固定 notice；score=101 → 502；verdict 越界 → 502
7. 策略：零数据 insufficient；有数据时聚合出现在 prompt、3 段齐全、缺段 422
8. workbench-summary / dashboard 全部字段来自现查 SQL（空库返回全 0/空数组，不报错）；dashboard 空数据 insufficient: true
9. doctor 18 项全跑通、value 非空；`gateway status --json` 机器可读；`gateway start` 明确说不适用
10. 全量 pytest ≥ 基线 858 + 新增；ruff 0 错误

## 6. 必测清单

- `atelier/tests/test_attribution.py`（新）：v8 三表在 fresh 库出现；快照 CRUD + 日期零填充 422；growth 0/1/2 条快照三分支（不足时 `fake.requests == []`）；metrics record 404 / platform 不一致 422 / 聚合正确；roi 负数 422、summary insufficient 与 roi_hint；comments-insight 短文本 422 不调模型、正常 JSON、themes 越界 502、BLOCK；review insufficient 不调模型、正常 4 段、缺段 422、sediment 写 memories（source=复盘沉淀）、不 sediment 不写、无画像 `profile_used: false`；predict notice 固定 + score 越界 502 + verdict 越界 502；strategy 零数据 insufficient + 正常 3 段 + 缺段 422；workbench-summary 空库全零 / 有数据计数正确 / scheduler 字段来自 get_status；dashboard 升序 / insufficient 空态 / platform 过滤；session 前缀 `attribution-<task>-`；画像注入（`fake.requests[0].profile`）
- `atelier/tests/test_db.py`：EXPECTED_TABLES +3；`SCHEMA_VERSION == 8`
- `atelier/tests/test_discovery.py`：两处 `schema_version() == 7` → 8
- `atelier/tests/test_skill_runs.py`：v1 老库迁移后表总数 19 → 22
- `atelier/tests/test_doctor.py`：17 → 18（数量断言、维度集合、报告行数、JSON total、main 分发）

## 7. 偏差与待办登记

- SPEC-00 §3 写「doctor 17 项检查」，本批 F-I5 兑现为第 18 项 `local_agents`（冻结数字 17 → 18，模块 docstring / help 同步）；后续 SPEC-00 修订时把该数字改为「按 CHECKS 注册表计数」或直接写 18
- PRD F-G30 的「昨日/上周/上月/去年同期」多口径对比落为「最近两条快照差值 + days 窗口过滤」：对比口径由录入节奏决定（隔天录 = 日环比，隔周录 = 周环比），不假装平台能给历史时点数据
- PRD F-G32「拉取评论」无公开 API，落地为**用户粘贴评论文本**后 AI 提取高频反馈；`count_hint` 字段名即「近似计数」契约，AI 不得输出精确统计数字
- PRD F-H1/F-H2 的页面（问候/状态卡/看板 UI）不在本批：只交付 §2 两个只读端点；前端批实现时必须消费 insufficient 字段渲染空态，不得自造数字
- F-I5「启用」外部 agent 未做（仅检测）：启用属 harness registry 扩展，当前 provider 只有 claude_sdk / mock（SPEC-01 §4），doctor hint 已如实标注
- `roi_entries.record_id` 不设外键（§1）：投入可先于发布记录存在；关联是可选的手工标注，不做引用完整性约束
