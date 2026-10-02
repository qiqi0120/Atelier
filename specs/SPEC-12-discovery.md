# SPEC-12 · 发现域收官 + 策划域 P3（M2-3b，M2 收官批）

| 项 | 值 |
|---|---|
| 版本 | v1.0 |
| 日期 | 2026-10-03 |
| 范围 | F-D5 博主订阅 · F-D6 深度加载 · F-D7 RSS 聚合 · F-D8 热点日报 · F-D11 内容缺口 · F-D12 算法追踪（P3）· F-D13 UGC 发现（P3）· F-E15 营销策划 / F-E16 直播策划 / F-E17 商单（P3）· 前端 `hot` 页转正 + workbench FEED 接真数据 + analytics 三卡 |
| 明确不含 | F-D1~D4 的「7 源自动热榜」（平台无公开热点 API，数据源决策仍悬——本批以**订阅聚合 + 手工导入**双数据源承接热点素材，固定 notice 如实标注；收藏到选题库 F-D3 与做成内容 F-D4 随 hot 页转正一并闭合）· accounts 页转正（归 M4 SPEC-14） |
| 依据 | `prd/PRD-Atelier-v1.0.md` §7 / §8 · `plans/PLAN-M2.md` §2 M2-3 · `specs/SPEC-09`（F-D8 的 `hot_digests` 表后移至此）· `specs/SPEC-11`（AI 任务模式先例） |

## 0. 已确认决策

| # | 决策 |
|---|---|
| D1 | **热点数据源诚实方案**：抖音/微博/小红书等均无公开热点 API，PLAN-M2 §2 的「数据源决策」本批落地为——数据源①RSS 订阅聚合（F-D5/D7，网络可达即真数据）；数据源②手工导入（粘贴热榜条目）。7 源自动热榜**不做假数据**，hot 页固定 notice 说明能力边界 |
| D2 | RSS 解析用**标准库 `xml.etree.ElementTree`** + `httpx` 拉取（RSS 2.0 + Atom 两种格式），不新增第三方依赖。解析失败/超时/非 RSS → `DiscoveryFetchFailed`(422) 附明确原因，不做静默空结果 |
| D3 | AI 任务（日报 digest / 内容缺口 gaps）复用 `topics.service` 原语（`run_ai_text(domain="discovery")` / `extract_json` / `gates_block_or_raise` / `AIOutputInvalid`），session 前缀 `discovery-<task>-`；insufficient 语义与 SPEC-11 一致——**数据不足不调模型** |
| D4 | **过滤去重是代码事实**：关键词过滤与 `(subscription_id, dedup_key)` 唯一索引去重在 SQL/代码层做，不信任模型。时间窗默认 7 天（`published_at` 缺失回退 `fetched_at`） |
| D5 | F-D12 算法追踪 = **手工登记时间线**（自动追踪无数据源，固定 notice）；F-D13 UGC 发现 = **订阅源内关键词搜索**（复用 `feed_items`，零新抓取逻辑）；F-D6 深度加载 = 对 RSS 源尽力多拉归档 + 对无 RSS 源明确「不支持自动抓取，请手填」 |
| D6 | F-E15/E16/E17 是纯 AI 策划任务，归 insights 域（同 F-E12~E14 语义）：Markdown 冻结段 + `InsightsIncomplete`(422)，**不落库**，前端 analytics 页三张工具卡 |
| D7 | 新表 5 张（schema v6）：`subscriptions` / `feed_items` / `hot_entries` / `hot_digests` / `algorithm_notes`。热点收藏进选题库复用既有 `POST /topics`（source=`hot`，source_ref=来源），**零新端点** |

## 1. 数据契约（schema v6）

| 表 | 列 | 说明 |
|---|---|---|
| `subscriptions` | id, name*, platform, kind*(blogger/media/newsletter), source*(rss/manual), url, keywords(TEXT, 逗号分隔), notes, enabled(INT 0/1 默认1), last_fetched_at, created_at, updated_at | source=rss 必须有合法 http(s) URL；source=manual 靠手填条目 |
| `feed_items` | id, subscription_id*(FK), title*, url, summary, published_at, fetched_at*, dedup_key* | UNIQUE(subscription_id, dedup_key)；dedup_key = guid 或 link（皆缺用 title 哈希） |
| `hot_entries` | id, title*, source*(rss/manual), platform, url, heat(TEXT 免费文本：排名/热度值), note, entry_date, status*(pending/digested/archived 默认 pending), digest_id, created_at, updated_at | 素材池；digest 后标 digested 并关联日报 |
| `hot_digests` | id, title*, window_start, window_end, markdown*, entry_ids(JSON), created_at | 日报只追加不改（重新生成 = 新日报） |
| `algorithm_notes` | id, platform*, noted_at*(日期), change*(变化内容), impact, source, created_at, updated_at | 手工登记 |

## 2. 服务与 API 契约

后端新目录 `atelier/server/discovery/`（`service.py` CRUD + `rss.py` 解析抓取 + `digest.py` 日报 + `gaps.py` 内容缺口）+ `api/discovery.py`。域内新错误：`DiscoveryFetchFailed`(422)、`DiscoveryIncomplete`(422，缺段同 SPEC-11 语义)，均定义在 `discovery/service.py`，不动 `errors.py`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/discovery/subscriptions` | 列表（kind/source/enabled 过滤）/ 新建（201；rss 源校验 URL） |
| PATCH/DELETE | `/discovery/subscriptions/{id}` | 改（keywords/enabled 等）/ 删（级联删其 feed_items） |
| POST | `/discovery/subscriptions/{id}/fetch` | 拉取单订阅：httpx GET（15s 超时）→ 解析 → 关键词+时间窗过滤 → 去重入库 → `{fetched, inserted, skipped}`；失败 → 422 带原因 |
| POST | `/discovery/fetch-all` | 逐个拉 enabled 的 rss 订阅，返回逐条结果（部分失败不整批失败） |
| POST | `/discovery/subscriptions/{id}/ingest` | manual 源手填：`{title*, url?, summary?, published_at?}` → feed_item（201） |
| POST | `/discovery/subscriptions/{id}/deep-load` | F-D6：rss 源尝试常见归档路径再多拉一轮并如实报告结果；manual 源 → 422「不支持自动抓取，请手填」 |
| GET | `/discovery/feed` | `subscription_id?/q?/days?(默认7)/limit?` 时间倒序 |
| GET/POST | `/discovery/hot` | 素材池列表（status 过滤）/ 手工导入（201） |
| POST | `/discovery/hot/from-feed` | `{ids*}`：feed_items 批量转素材池（source=rss，去重防重复转入） |
| POST | `/discovery/hot/digest` | AI 日报：pending 条目数 = 0 → `{insufficient: true, message}` **不调模型**；否则代码聚合素材 → Markdown 冻结 3 段（`热点盘点` / `机会点` / `建议动作`）→ 缺段 422 → 门禁 → 落 `hot_digests` + 条目标 digested |
| GET | `/discovery/hot/digests`（列表）、`/discovery/hot/digests/{id}` | 日报历史/详情（markdown 渲染） |
| GET/POST/DELETE | `/discovery/algorithm-notes` | 时间线（noted_at 倒序）/ 登记（201）/ 删 |
| GET | `/discovery/ugc` | `q*`：feed_items 全文搜索 + 按 subscription 标注来源（「来自订阅 ×××」） |
| POST | `/discovery/gaps` | 内容缺口：feed_items = 0 → `{insufficient: true, message}` 不调模型；否则代码算「订阅关键词频次 Top（竞品在写）vs 本方 topics 标题词频（我在写）」注入 prompt → JSON `{"gaps":[{"direction","demand","evidence","action"}]}` 1..6 条、单项 ≤80 字（越界 502）→ 门禁 → 不落库 |

端点同步 CRUD 用 def、AI 端点 async；字面路由声明在 `/{id}` 之前；不改 `main.py`（`_autoload_routers` 自动挂载）。

## 3. 策划域 P3（insights 扩展，F-E15/E16/E17）

| 任务 | 输出契约（Markdown 冻结段，缺段 → `InsightsIncomplete`） | 前端 |
|---|---|---|
| F-E15 营销策划 `POST /analytics/campaign` `{theme*, occasion?(节日/大促/新品), profile_id?}` | 5 段：`活动目标` / `主题创意` / `节奏排期` / `渠道分工` / `预算与KPI` | analytics 三卡 + 三弹层（复用 StrategyDialog 同构） |
| F-E16 直播策划 `POST /analytics/liveplan` `{topic*, duration?(分钟), profile_id?}` | 5 段：`直播目标` / `流程脚本` / `话术要点` / `互动设计` / `风险预案` | 同上 |
| F-E17 商单方案 `POST /analytics/sponsorship` `{brief*, brand?, profile_id?}` | 5 段：`合作解读` / `创意方案` / `内容形式` / `报价建议` / `风险与边界` | 同上 |

三工具不落库、过门禁、画像走 `TurnRequest.profile` 通道（无画像 = 通用模式 prompt 注入），session 前缀 `insights-campaign-` / `insights-liveplan-` / `insights-sponsorship-`。

## 4. 前端

- **`web/src/features/hot/` 转正**（删 M2Placeholder 依赖）：Tab 双视图——「素材池」（默认）：条目列表（来源/状态 Chip、热度、entry_date）、手工导入弹层、从订阅转入选择弹层、生成日报 primary 弹层（AI 三态同构）、日报历史抽屉（markdown 渲染）、每条目「存选题库」（POST /topics source=hot）与「做成内容」（fillPrompt → /chat）；固定 notice「7 源自动热榜无公开数据源，当前支持订阅聚合 + 手工导入」；「订阅源」Tab：订阅 CRUD + keywords 编辑 + 立即抓取（结果 toast：新增 N 条）+ 全部抓取 + feed 条目列表 + 手填弹层 + UGC 搜索框
- **workbench**：`FEED` mock 数组替换为 `GET /discovery/hot`（pending，limit 6），空态显示引导文案；NavGroups hot 的静态 count 删除（真实计数不为此单开请求，避免每页加载都打后端）
- **analytics**：新增三张 P3 工具卡（营销策划/直播策划/商单）+ 各自弹层（同构 StrategyDialog），页面说明更新
- `api.ts`/`types.ts` 域内自带；`test/routes.test.tsx` 导航断言不受影响（无新增路由）

## 5. 验收标准

1. 添加 RSS 订阅 → 抓取 → 条目按关键词/时间窗过滤去重入库，重复抓取 inserted=0
2. feed 条目一键转热点素材池 → 生成日报（3 段齐全，素材池空时明确「无可 digest 的素材」而非编造）
3. 素材条目可存入选题库（source=hot 可溯源）并一键做成内容
4. 内容缺口：无订阅数据时诚实提示不调模型；有数据时给出「高需求低竞争」方向与证据（证据来自代码统计，AI 只解读）
5. 算法追踪为手工时间线并如实标注；UGC 搜索能按关键词在订阅内容里找到条目并标注来源
6. 营销/直播/商单三工具缺段报错不硬编；全部 AI 产出过门禁，BLOCK 给改法

## 6. 必测清单

- `atelier/tests/test_discovery.py`：v5→v6 迁移（老库升级、老数据保留）；订阅 CRUD + rss 无 URL 422；RSS/Atom 解析（monkeypatch httpx 假响应）+ 关键词过滤 + 去重（二次抓取 inserted=0）+ 坏 XML/超时 → `DiscoveryFetchFailed`；手填 ingest；deep-load manual 源 422；hot CRUD + from-feed 去重；digest insufficient 不调模型（`fake.requests == []`）+ 正常 3 段 + 缺段 422 + 落库 digested + BLOCK 422；gaps insufficient + JSON 越界 502 + 证据注入 prompt 断言；algorithm-notes CRUD；ugc 搜索
- `atelier/tests/test_insights.py` 追加：campaign/liveplan/sponsorship 缺段 422、全段 200、画像注入与 session 前缀、BLOCK
- `web/src/features/hot/__tests__/hot.test.tsx`：双 Tab 渲染、导入弹层请求体、日报 insufficient 空态、存选题库请求体（source=hot）、BLOCK 改法展示
- `analytics.test.tsx` 追加：三卡渲染 + 一个弹层的缺段 422 展示

## 7. 偏差与待办登记

- PLAN-M2 §2 M2-3 预估的 `discovery/**` + `api/discovery.py` 本批兑现；`subscriptions / competitors / content_gaps` 三表中 `competitors` 不建（竞品分析 SPEC-11 已按即席咨询实现，无持久化需求），内容缺口结论同样不落库
- F-D1~D4 的 7 源自动热榜仍缺数据源——SPEC-09 §7 登记的「F-D8 后移待数据源决策」在本批以 D1 方案闭合，自动热榜归入 M5 之后的「数据源」专项（需真实账号/风控评估）
- F-D6 深度加载对抖音无公开源，PRD 的「增量翻页」语义落地为「RSS 归档尽力拉取 + 诚实告知」，不假装能翻页抖音
