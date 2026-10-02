# SPEC-10 · 选题链路收口（M2 收尾）

| 项 | 值 |
|---|---|
| 版本 | v1.0 |
| 日期 | 2026-10-03 |
| 范围 | F-E3 选题一键成内容（P0）· F-E4 选题排期（P0）· F-E5 内容日历（P0，最小完整态）——SPEC-09 §9 登记的 P0 悬空项在本批全部闭合 |
| 不含 | F-G20 定时发布（M4）：本批的排期是**内容日历上的人工计划日**（纯元数据），不是平台定时发送；`hot` 来源选题（M2-3）；选题→草稿的自动产物关联（创作链路自动打标属后续批） |
| 依据 | `prd/PRD-Atelier-v1.0.md` §8（F-E3/E4/E5 + §8.1 验收 3）· `specs/SPEC-08` §9 · `specs/SPEC-09` §9 |

## 0. 已确认决策

| # | 决策 |
|---|---|
| D1 | **F-E3 纯前端**：选题卡「做成内容」→ `fillPrompt`（`lib/store` 既有机制，能力卡/热点同款）+ 跳 `/chat`，**只填入不自动发送**（UI-SPEC 规则 1）。prompt 模板内联标题/角度/画像平台；产出不经选题域，落对话→产物→内容库的既有链路 |
| D2 | **F-E4 后端已就绪**（SPEC-09 已交付 `PATCH /topics/{id}` 的 `due_date`）；本批只补 UI：选题卡「排期」动作（日期弹层：设置/清空），日历与看板双入口 |
| D3 | **F-E5 靠关联不靠新状态机**：`publish_drafts` 补两列 `topic_id`（关联选题，可空）、`scheduled_date`（计划发布日，`YYYY-MM-DD` 可空，语义见下），schema v3→v5 走 `_EXPECTED` 自动补列；**不建新表、不加状态字段** |
| D4 | PRD 四态流转的**诚实映射**（无日期的条目不上日历）：**选题** = topic 有 `due_date` 且无关联草稿；**草稿** = 关联草稿存在但未排期（只在发布中心可见，不上日历）；**待发** = 草稿已排期、无发布记录；**已发** = 草稿存在 `publish_records`。日历展示选题/待发/已发三态，草稿态在发布中心——四态全有归处，日历上无编造条目 |
| D5 | `topic_id` 写入时校验选题存在（不存在 404）；**不级联**：删选题不动草稿（草稿的 `topic_id` 保留为悬空引用，日历侧容忍——按「关联已失效」降级为无关联草稿处理）；`""` 清空，`null`/缺省不动（与 due_date 约定一致） |
| D6 | `scheduled_date` 校验复用 `topics.service.validate_due_date`（零填充 ISO 或空）；日历查询窗口判定与 `due_date` 同款 BETWEEN |
| D7 | 日历月视图响应扩展：`topics[]` 条目附 `stage`（`topic`/`ready`/`published`）与 `draft_id`（可空）；新增 `drafts[]`（`scheduled_date` 落当月的草稿，附 `stage`、`topic_id`、`topic_title`）。stage 由代码按 D4 推导，前端不重复判断 |

## 1. 数据契约（schema v5）

`publish_drafts` 加两列（`_EXPECTED["publish_drafts"]` 同步，`_DDL` 建表文本同步给全新库）：

```sql
topic_id TEXT,        -- 关联选题（可空；SPEC-10 §0 D5）
scheduled_date TEXT   -- 计划发布日 YYYY-MM-DD（可空；人工排期，非平台定时发送）
```

`SCHEMA_VERSION 4→5`；`_apply_v5` 为**版本标记步**（实际补列由 migrate 末尾 `_add_missing_columns` 依 `_EXPECTED` 统一执行，同 v4 的 due_date 先例），保证老库 `user_version` 前进可判。索引不新增（草稿量级不需要）。

## 2. API 契约

| 方法 | 路径 | 变更 |
|---|---|---|
| POST | /publish/drafts | `DraftCreate` 增 `topic_id?`、`scheduled_date?`；`topic_id` 非空时校验选题存在 |
| PATCH | /publish/drafts/{id} | `DraftPatch` 增 `topic_id?`、`scheduled_date?`；语义同 D5/D6 |
| GET | /calendar?month= | 响应增 `drafts`，`topics` 条目增 `stage`/`draft_id`（D7） |

草稿响应体（`PublishDraft` 模型与 `_row_to_draft`）随之增两字段。错误沿用统一错误体，不新增错误码。

## 3. 前端

- **topics 看板**：卡片操作区增「排期」（CalendarPlus 图标 → 日期弹层：`<input type=date>` + 保存/清空）与「做成内容」（Wand 图标 → D1）；`due_date` chip 保持只读展示
- **发布中心 MasterEditor**：话题标签行下方增「排期与关联」行——计划发布日 `<input type=date>`（变更即存）+ 关联选题 Select（可空，选项来自 `GET /topics`，懒加载一次）；两者走既有 `onSave` 通道，自动保存文案不变
- **日历页**：内容条目按 `stage` 加文字徽标（选题 / 待发 / 已发，`Chip xs`）；`drafts[]` 以待发/已发样式渲染进月格与近期条；点击路由——`stage=topic` → `/topics`，其余 → `/publish`；图例文案同步
- 零新依赖、零新颜色；弹层复用基础组件

## 4. 验收标准（对照 PRD §8.1）

1. 选题卡「做成内容」→ 对话页输入框已填入选题上下文且**未自动发送**，画像平台名在 prompt 里
2. 选题卡「排期」设置日期 → 看板 chip、日历月格、`GET /topics` 三处一致；清空后三处同步消失
3. 草稿排期 + 关联选题后，日历当月出现「待发」条目（带选题标题溯源）；产生发布记录后同一条目变「已发」
4. 删除已关联的选题：草稿不删，日历条目降级为无关联草稿（不报错、不悬空崩溃）
5. 日历仍能区分内容条目与平台活动（SPEC-09 交付，回归不破）

## 5. 必测清单

`test_publish.py` 增：create/patch 收 `scheduled_date`/`topic_id`；坏 topic_id → 404；`""` 清空、缺省不动；响应体含两新字段。
`test_calendar.py` 增：当月 `drafts`（排期草稿入列、跨月不串）；topic `stage` 三态推导（无草稿/待发/已发）；删选题后 stage 降级不炸。
`test_db.py`：`SCHEMA_VERSION == 5`；v4 老库 migrate → v5、旧草稿数据完整、新列可空；`_DDL` 与 `_EXPECTED` 列一致。
前端：topics 测试增「排期弹层提交 PATCH due_date」「做成内容 fillPrompt + 跳转且不发送」；calendar 测试增 stage 徽标与 drafts 条目、点击路由分流；publish 测试增排期/关联控件触发 patch。

## 6. 偏差与待办登记

- PRD F-E5 的「状态流转」原文含四态上日历；本批落为**三态上日历 + 草稿态留发布中心**（D4：无日期条目不上日历是日历的物理约束，不是砍功能）
- 选题→草稿关联目前靠发布中心手工选；F-E3 创作链路**不自动**回填 `topic_id`（对话产物→内容库→挂载草稿的自动打标属后续批，涉及 MCP 工具上下文传递）
- `MasterEditor` 的关联选题下拉懒加载全量选题（≤200 条场景无分页）；超大规模再谈虚拟化
