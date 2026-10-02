# SPEC-08 · 选题域（M2-1）

| 项 | 值 |
|---|---|
| 版本 | v1.0 |
| 日期 | 2026-10-02 |
| 范围 | `plans/PLAN-M2.md` §2 M2-1：F-E8 爆款拆解（P0）· F-E9 选题评分 · F-E10 内容矩阵 · F-E11 标题 Hook |
| 顺带覆盖 | F-E1 选题库 / F-E2 选题 CRUD 的**最小可用**（看板三态 + 增删改查）——M2-2 日历建议与 M2-1 矩阵都要落「选题池」，池本体在本 spec 冻结 |
| 依据 | `prd/PRD-Atelier-v1.0.md` §7/§8 · `specs/SPEC-00` §3 · `plans/PLAN-M2.md` |

## 0. 已确认决策

| # | 决策 |
|---|---|
| D1 | AI 调用走 `harness.registry.get_harness()` 流式收集文本（同 `skills/runner._run_via_harness` 模式）；**不 import SDK、不落产物文件** |
| D2 | 拆解 6 段式按 **PRD F-E8** 冻结：概括 / 钩子 / 结构 / 为何火 / 可复制模板 / 结合画像出选题。现有 `skills/viral-decode`（chat 入口，6 段名不同）不在本批改动，口径对齐记 §9 待办 |
| D3 | 评分结论（做/不做/改方向）由**代码按总分判定**，不由模型自报——与门禁同理，不信任模型自评 |
| D4 | 字数校验一律经 `gates/wordcount.count_platform_chars`，不得另写计数（PLAN-M2 §2 复用提醒） |
| D5 | 选题状态枚举：`todo / doing / done`（UI 映射 待做/进行中/已完成）；来源枚举：`manual / decode / matrix`（`hot / calendar` 留给 M2-2/M2-3，本批写库时拒绝） |

## 1. 数据契约（schema v3）

```sql
CREATE TABLE topics (
  id TEXT PRIMARY KEY,
  profile_id TEXT,            -- 可空 = 通用模式
  title TEXT NOT NULL,        -- 1..80 字（strip 后）
  angle TEXT,                 -- 备注角度 ≤200 字
  source TEXT NOT NULL,       -- manual | decode | matrix
  source_ref TEXT,            -- 来源引用：拆解=原文首行、矩阵=pillar×format、手填=空
  status TEXT NOT NULL,       -- todo | doing | done
  decode TEXT,                -- 拆解结果 markdown（仅 source=decode 时允许非空）
  created_at TEXT, updated_at TEXT
);
CREATE TABLE topic_scores (
  id TEXT PRIMARY KEY,
  topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  dims TEXT NOT NULL,         -- JSON，7 维整数 1..5（见 §3）
  total INTEGER NOT NULL,     -- 7..35，代码求和
  verdict TEXT NOT NULL,      -- do | pivot | dont（代码按 §3 阈值判定）
  reason TEXT,                -- 模型给出的一句话理由
  created_at TEXT
);
```

索引：`idx_topics_profile(profile_id, status)`、`idx_topic_scores_topic(topic_id, created_at)`。
迁移走 `db._MIGRATIONS[3]`，不动 v1/v2 步骤。

## 2. AI 任务契约（三个任务共用一条调用路径）

共用：`TurnRequest(session_id="topics-<task>-<uuid8>", profile=store.get_profile(profile_id) 或 None,
system_suffix=任务专用说明)`，流式收集 `TEXT_DELTA` 到 `DONE`；`ERROR` 事件 → 抛 `HarnessError`。
画像注入交给你 harness 的 `profile` 通道（SPEC-02 §4），本域不手工拼画像文本。

| 任务 | 输入 | 模型输出约定 | 解析失败 |
|---|---|---|---|
| decode | 原文（≥40 字，沿用 viral-decode 的「拆不动」阈值）、metrics?、platform?、goal? | Markdown，6 个 `##` 段，段名含关键词：概括/钩子/结构/为何火/可复制模板/结合画像 | 缺任一段 → `DecodeIncomplete`(422)，detail 列缺哪些段 |
| score | topic（必已入库） | 严格 JSON：`{"dims":{traffic,match,differentiation,timing,monetization,cost,risk}, "reason":"…"}`，每维 1–5 整数，risk 高分=低风险 | JSON 解析失败或维度缺/越界 → `AIOutputInvalid`(502) |
| matrix | pillars(1..6) × formats(1..6) × per_combo(1..3) | 严格 JSON：`{"items":[{"pillar","format","title","angle"}]}`，title ≤80 字 | 同上；`pillars×formats×per_combo > 60` 先在参数层拒绝（422），不调模型 |
| hooks | title（直接给或取 topic.title）、platform? | 严格 JSON：`{"variants":[{"text":…}]}`，3–5 条 | 同上 |

**JSON 提取容错**：剥 ``` 围栏后取首个 `{` 到末个 `}`；仍失败按上表报错，不编造。
**model 输出一律不落产物文件**，入库的是结构化字段与 markdown 文本。

## 3. 评分判定（确定性，代码持有）

- 7 维中文序：流量潜力 / 账号匹配 / 竞争差异化 / 时效 / 变现 / 成本 / 风险（5 分 = 低风险）
- `total = sum(dims)`，区间 7..35
- verdict 阈值（冻结）：`total ≥ 27 → do`；`total ≤ 18 → dont`；其余 `→ pivot`
- 每次评分**追加**一条 `topic_scores`（保留历史）；`GET /topics/{id}` 返回最新一条

## 4. 门禁接线（产出先过门禁，PLAN-M2 §3）

| 产出 | 跑哪些门禁 | BLOCK 处理 |
|---|---|---|
| decode 全文 | `compliance + secret_scan + ai_flavor` | `GateBlocked`，detail 带 `gate_report`（ai_flavor 是 WARN 只附带不阻断） |
| matrix 全部标题（换行拼接） | 同上 | 同上（整批拒绝，重试即整批重来，不做静默过滤） |
| hooks 全部变体文本（换行拼接） | 同上 | 同上 |
| hooks 每条变体 | `count_platform_chars(text)` vs 平台上限 | 不抛错：逐条标 `passed`。platform 缺省按 **dy 55 从严**（钩子本质是标题，沿 wordcount 门禁「未指定从严」先例） |

## 5. API 契约（`api/topics.py`，`/api` 前缀由 main 统一加）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /topics?profile_id=&status=&q= | 池列表（updated_at 倒序），`{items, total}` |
| POST | /topics | `{title*, angle?, profile_id?, source?, source_ref?, decode?}` → 201。`decode` 仅 `source=decode` 时接受，否则 422 |
| GET | /topics/{id} | `{topic, score}`（score=最新一条，可为 null） |
| PATCH | /topics/{id} | `{title?, angle?, status?}` → topic。status 非法值 422 |
| DELETE | /topics/{id} | `{ok, id}`；不存在 404 |
| POST | /topics/decode | `{text*, metrics?, platform?, goal?, profile_id?}` → `{decode_markdown, sections, gate_report, topic_seed}`；**不落库**，保存走 POST /topics |
| POST | /topics/score | `{topic_id*, profile_id?}` → 201 最新评分 |
| POST | /topics/matrix | `{pillars*, formats*, per_combo?, profile_id?}` → 201 `{items, count}`，全部入库（status=todo, source=matrix） |
| POST | /topics/hooks | `{topic_id? \| title*, platform?}` → `{variants:[{text, chars, limit, passed}]}`，不落库 |

错误体沿用 SPEC-01 §2 `{error:{code,message,detail,hint}}`。本批新增错误：`DecodeIncomplete`(422)、`AIOutputInvalid`(502)，定义在 `topics/service.py`（不动 `errors.py`）。

## 6. 前端（`web/src/features/topics/`，占位页转正）

- 单页三区：顶部工具条（新建选题=primary、爆款拆解、生成矩阵）+ 三列看板（todo/doing/done）+ 卡片操作（评分 / 起标题 / 改状态 / 删除）
- 拆解、矩阵、评分、Hook 全部走弹层（Modal），沿用基础组件，零新依赖
- `api.ts`/`types.ts` 域内自带，走 `lib/api.ts` 的 `ApiError` 自动 toast；`handled: true` 仅用于门禁 BLOCK 弹层内展示改法

## 7. 验收标准（对照 PLAN-M2 §2 M2-1 出口）

1. 粘贴对标内容 → 6 段式拆解（概括/钩子/结构/为何火/可复制模板/结合画像出选题），缺段报错不硬编
2. 选题按 7 维打分 + 「做/不做/改方向」明确结论；结论阈值由代码判定且可测
3. 内容矩阵（支柱 × 格式）一键生成选题池并入库，可在看板看到
4. 标题 Hook 出多变体，每条带字数与是否超限（口径来自 `gates/wordcount`）
5. 拆解结果可一键存入选题库（source=decode，原文溯源 source_ref）

## 8. 必测清单（`atelier/tests/test_topics.py`）

- CRUD 全链路 + 404/422；source 非法值拒绝
- decode：6 段齐 → sections 全 true；缺段 → 422 且列缺段；<40 字 → 422；BLOCK 词 → GateBlocked 且 detail 带 gate_report
- score：JSON → 201 且 total/verdict 与 §3 阈值一致（三档各一条）；坏 JSON → 502；维度越界 → 502；topic 不存在 → 404
- matrix：2×2×2=8 条入库；>60 组合 → 422（不调模型）；BLOCK 词 → 422
- hooks：chars 与 `count_platform_chars` 一致；dy 55 上限判定正确；缺 title 且缺 topic_id → 422
- schema：user_version=3，两表两索引存在；score 级联删除
- AI 调用统一走 fake harness（同 test_chat 模式），断言 TurnRequest.profile 注入与否

## 9. 偏差与待办登记

- PLAN-M2 §2 预估模块为 `{service,decode,score,matrix}.py`，实际加 `hooks.py` 共 5 个（hooks 独立成模块，不塞进 score）——规模预估内的偏差，不是契约变更
- `skills/viral-decode/SKILL.md` 的 6 段名与 PRD F-E8 不同：chat 入口与页面入口暂存两套拆解口径，**后续批**统一（倾向技能向 PRD 对齐），本批不动既有技能
- M2-1 不含 F-E3（选题一键成内容）与 F-E4（排期）——E3 依赖对话预置 prompt 链路、E4 依赖 M2-2 日历，分别记入后续
