# SPEC-09 · 日历与建议（M2-2 前半）

| 项 | 值 |
|---|---|
| 版本 | v1.0 |
| 日期 | 2026-10-02 |
| 范围 | `plans/PLAN-M2.md` §2 M2-2 中**不依赖外部数据源**的部分：F-D9 事件日历 · F-E6 平台活动日历 · F-E7 日历建议 |
| 明确不含 | F-D8 热点日报（依赖热点数据源，方案待 Mr Yu 确认后另立 spec）；`hot_digests` 表本批不建 |
| 顺带覆盖 | topics 域预留扩展的兑现（`source=calendar` + `due_date`，SPEC-08 §0 D5 预留）；F-E4/F-E5 的**最小底座**（仅数据列与日历只读展示，完整态另立 spec） |
| 依据 | `prd/PRD-Atelier-v1.0.md` §7/§8 · `specs/SPEC-00` §3 · `plans/PLAN-M2.md` §2 · `specs/SPEC-08`（预留位） |

## 0. 已确认决策

| # | 决策 |
|---|---|
| D1 | AI 调用**复用** `topics/service.py` 的三个原语：`run_ai_text`（加 `domain` 形参，默认 `"topics"`，既有调用不变）、`extract_json`、`gates_block_or_raise`。不 import SDK、不落产物文件，流式收集到 `DONE` |
| D2 | `calendar_events` 是**全局表，不带 `profile_id`**：节日/平台活动不属于某个画像。建议出的选题才绑画像（`create_topic(profile_id=…)`），建议时画像只进 `TurnRequest.profile` 通道 |
| D3 | 建议落池 `source=calendar`、`due_date=建议日期`、`source_ref=引用的事件名`（可空）。SOURCE 枚举扩展是 SPEC-08 预留位的兑现，不是契约变更 |
| D4 | 内置节点只含**公历确定日 + 可计算的**母亲节/父亲节（按年算出具体日期）；农历节日（春节/中秋/端午/清明/七夕/年货节）不内置、**不引农历依赖**，用户手工添加。导入是**显式动作**（POST /calendar/seed），按 `(title, date)` 幂等补种；删除内置条目后重新导入会带回——语义就是「重新导入」 |
| D5 | 「提前 N 天提醒」是**查询式**，不做后台推送/通知/定时器：`GET /calendar/upcoming` 由前端拉取，每条事件自带 `remind_days`（0..30，默认 3） |
| D6 | 平台活动**手工录入**（无自动数据源）。UI-SPEC 规则 15 的斜纹虚线样式照做；「只读」语义落为「不可拖拽成内容」（本批日历本就无拖拽），可正常编辑/删除 |
| D7 | 日期一律 `YYYY-MM-DD` 零填充 ISO 文本；「今天」固定走**北京时间**（`calendar/service.local_today()`，节假日/大促语义本就以中国日历为准，也消除机器时区差异）；服务层函数带 `today` 形参保证可测 |

## 1. 数据契约（schema v4）

```sql
CREATE TABLE IF NOT EXISTS calendar_events (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,        -- 1..80 字（strip 后）
  date TEXT NOT NULL,         -- YYYY-MM-DD
  end_date TEXT,              -- 可空；多日活动（平台活动常用），须 >= date
  kind TEXT NOT NULL,         -- festival | ecommerce | industry | platform
  note TEXT,                  -- ≤200 字
  remind_days INTEGER NOT NULL DEFAULT 3,
  source TEXT NOT NULL,       -- builtin | manual
  created_at TEXT, updated_at TEXT
);
```

索引：`idx_calendar_date(date)`。
另：`topics` 表加**可空列** `due_date TEXT`——`_EXPECTED["topics"]` 同步加列即可，`_add_missing_columns`（migrate 末尾自动跑）会用默认 `ADD COLUMN … TEXT` 给 v3 老库补上，无需写 ALTER。`SCHEMA_VERSION 3→4`；`_apply_v4` 只负责建 `calendar_events` 表 + 索引，不动 v1/v2/v3 步骤。

## 2. AI 任务契约（唯一任务：suggest）

共用：`run_ai_text(domain="calendar", task="suggest", …)` → `TurnRequest(session_id="calendar-suggest-<uuid8>", profile=store.get_profile(profile_id) 或 None, system_suffix=任务专用说明)`；画像注入走 harness 的 `profile` 通道（SPEC-02 §4），本域不手工拼画像文本。

| 任务 | 输入 | 模型输出约定 | 解析失败 |
|---|---|---|---|
| suggest | 窗口内事件清单（title/date/kind/note）+ days + 画像（可空） | 严格 JSON：`{"items":[{"date","title","angle","event"}]}`。`date` 必须落在窗口内且尽量贴合相关事件；`title` 1..80 字；`angle` ≤200 字；`event`=引用的事件名（通用建议可为空）；条数 1..30（prompt 提示 5..15） | JSON 解析失败、字段缺失/越界、`date` 越窗、条数越界 → `AIOutputInvalid`(502)（复用 topics 的错误类，**本批不新增错误码**） |

窗口内**没有事件也允许生成**（纯画像通用建议），prompt 如实告知「窗口内无节点」。重复生成会产生重复选题，**不做去重**（与矩阵同语义，用户自行清理）。

## 3. 提醒窗口规则（确定性，代码持有）

- 提醒激活：`today ≥ date − remind_days` **且** `today ≤ COALESCE(end_date, date)`
- `days_left = (date − today).days`：`>0` 显示「还有 N 天」；`=0`「今天」；`<0` 且未过 `end_date` → 「进行中」
- `GET /calendar/upcoming?days=N` 返回 `[today, today+N−1]` 内的事件（默认 14，与建议窗口一致），按 `date ASC` 排序，每条附 `remind_active` 与 `days_left`

## 4. 门禁接线（产出先过门禁，PLAN-M2 §3）

| 产出 | 跑哪些门禁 | BLOCK 处理 |
|---|---|---|
| 建议全部 title + angle（换行拼接） | `compliance + secret_scan + ai_flavor` | `GateBlocked`(422)，detail 带 `gate_items`（ai_flavor 是 WARN 只附带不阻断）——走 `gates_block_or_raise`，**整批拒绝**，重试整批重来，不做静默过滤 |

（无 hooks 式逐条字数判定：建议不是发布文案，字数校验属后续成稿环节。）

## 5. API 契约（`api/calendar.py`，`/api` 前缀由 main 统一加）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /calendar?month=YYYY-MM | 当月条目 `{events, topics}`；events 按 `(date ≤ 月末) AND (COALESCE(end_date,date) ≥ 月初)` 重叠判定；topics = `due_date` 落在当月的选题（全状态）。month 缺省取当月 |
| POST | /calendar | `{title*, date*, end_date?, kind*, note?, remind_days?}` → 201，`source=manual` |
| PATCH | /calendar/{id} | `{title?, date?, end_date?, kind?, note?, remind_days?}` → event；不存在 404 |
| DELETE | /calendar/{id} | `{ok, id}`；不存在 404；内置条目同样可删 |
| GET | /calendar/upcoming?days= | §3 规则，`{today, items}` |
| POST | /calendar/seed | `{year?}`（缺省当年）→ `{added, skipped}`，只补种 `(title, date)` 不存在的内置节点 |
| POST | /calendar/suggest | `{profile_id?, days?}` → 201 `{items: [topic], count}`，全部落池（status=todo, source=calendar） |

校验：`kind` 非法 / `date` 非 ISO / `end_date < date` / `remind_days` 越界（0..30）/ title 空、>80 / note >200 → 422 `ValidationError`。
字面路由（`upcoming`/`seed`/`suggest`）必须声明在 `/{id}` 之前。错误体沿用 SPEC-01 §2。

## 6. 前端（`web/src/features/calendar/`，占位页转正）

- 单页三区：顶部工具条（**生成近 14 天建议 = primary**（UI-SPEC §6 /calendar 主行动）· 新建事件 · 导入本年节点 · 月份切换 ‹ ›）+ 月视图网格 + 近期节点条
- 月格沿用 `global.css` 原型已备好的 `cal-*` / `ev` / `ev.act` 样式，**零新增 CSS**。格内条目两类：选题条目（`.ev` accent 边框 = 「内容条目」，点击跳 `/topics`）；日历节点（`.ev.act` 斜纹虚线 = 「非内容条目」统一只读视觉，D6，点击进编辑弹层），kind 用**文字前缀**（节/促/业/活）区分，不引入新颜色
- 近期节点条：`remind_active` 的条目用 accent Chip，文案区分「还有 N 天 / 今天 / 进行中」
- 弹层：`EventDialog`（新建/编辑/删除三合一，删除走 `ConfirmDialog`）；`SuggestDialog`（画像跟随当前激活画像——与拆解/矩阵弹层一致 + 天数默认 14；结果列表展示 title/date/event）；门禁 BLOCK 的 `gate_items` 展示走 `lib/gates.describeError`（describe.ts 已从 topics 域上移 `lib/gates.ts`——门禁报告是 API 契约，归 lib）
- `api.ts`/`types.ts` 域内自带，走 `lib/api.ts` 的 `ApiError` 自动 toast；`handled: true` 仅用于门禁 BLOCK 弹层内展示改法
- topics 看板卡片副行：`due_date` 非空时显示 `MM-DD` chip（TopicsPage 一处小改）

## 7. 验收标准（对照 PLAN-M2 §2 M2-2 出口）

1. 节日/电商节点/行业事件/平台活动可建/改/删入日历，月视图正确呈现；平台活动斜纹样式与内容条目可区分
2. 「导入本年节点」一键补种内置节日/电商节点，重复导入幂等（added/skipped 如实）
3. 提前提醒：近 N 天面板列出将到节点，进入提醒期的条目有「还有 N 天」标记，多日活动提醒期延续到 end_date
4. 「生成近 14 天建议」→ AI 基于窗口内事件 + 画像出建议 → 直接落选题池（source=calendar、due_date=建议日期、可溯源到事件名），看板与日历都能看到
5. 全程**无外部数据源依赖**：不抓取任何远端；F-D8 热点日报明确不在本批

## 8. 必测清单

`atelier/tests/test_calendar.py`（fake harness 复用 test_topics 的 `ScriptedHarness`/`fake`/`client`——上移 `conftest.py` 或显式 import，**不许复制第二套**）：

- CRUD 全链路 + 404/422：kind 非法、date 非法、end_date < date、remind_days 越界、title 空/>80
- month 查询：单日落当月；跨月 end_date 两侧月份都能看到
- upcoming：窗口裁剪；remind_active 边界（today = date − remind_days 当天激活；多日活动延续到 end）；days_left 三态
- seed：默认当年；added/skipped 计数；二次幂等；删除内置后 re-seed 带回（D4 文档化行为）；母亲节/父亲节按年计算正确（2026 → 05-10 / 06-21）
- suggest：JSON 齐 → 201 且落池断言（source=calendar、due_date、source_ref=事件名、status=todo）；画像注入断言（`TurnRequest.profile` + session_id 前缀 `calendar-suggest-`）；坏 JSON → 502；date 越窗 → 502；条数越界 → 502；BLOCK 词 → 422 且 detail 带 gate_items；窗口内无事件仍可生成
- topics 扩展回归：POST /topics 收 `source=calendar`；`source=hot` 仍 422；due_date 合法/非法（422）/PATCH 清空
- schema：user_version=4；calendar_events 在表清单；topics 含 due_date；v3 库迁移到 v4 后旧数据完整、新列可空；test_db 表清单 12→13、test_skill_runs 的 v1→v2 计数同步

`web/src/features/calendar/__tests__/calendar.test.tsx`：月视图渲染当月条目；新建事件提交；删除走确认；导入节点调 seed 并刷新；建议弹层提交参数与结果渲染；platform 条目有斜纹 class；选题条目跳 /topics；提醒徽标文案。

## 9. 偏差与待办登记

- PLAN-M2 §2 M2-2 预估新表 `calendar_events`/`hot_digests`——**hot_digests 本批不建**（F-D8 整体后移，见下条）；预估模块 `{service,suggest}.py` 照做，内置节点数据内嵌 `service.py` 常量，不加新模块
- **F-D8 热点日报不在本 spec**：数据源方案（RSS / 第三方聚合 / 手工导入）待确认后另立 SPEC-10，PLAN-M2 的 M2-2 出口标准第 2 条随之顺延
- **F-E4 选题排期 / F-E5 内容日历完整态仍不在本批**：本批只交付 `due_date` 列 + 日历只读展示选题的最小底座。两者是 PRD P0，需在 M2 收尾前补 spec，否则 P0 悬空——在此显式登记，避免验收时误判
- topics 域契约扩展（兑现 SPEC-08 §0 D5 预留位，共四处）：`SOURCE_VALUES` + `calendar`；`create_topic` / PATCH / POST 收 `due_date`；`row_to_topic` + `due_date`；`run_ai_text` 加 `domain` 形参（默认 `"topics"`，既有调用不变）
- UI-SPEC 规则 15「平台活动只读」原预设自动数据源；无源现状下降级为**手工录入 + 同款斜纹视觉**，「只读」语义落为不可拖拽成内容（D6）
- 内置节点仅公历确定日 + 母亲节/父亲节；农历节日不内置、不引农历依赖（D4，零新依赖铁律）
