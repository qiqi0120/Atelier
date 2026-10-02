# SPEC-14 · 平台扩展与发布增强（M4）

| 项 | 值 |
|---|---|
| 版本 | v1.0 |
| 日期 | 2026-10-03 |
| 范围 | F-G19 平台优化建议 · F-G20 定时发布 · F-G21 短链 · F-G22~G28 账号登录中心（accounts 页转正）+ 新增 4 平台（快手/知乎/B站/微信视频号） |
| 明确不含 | **真实发布与真实扫码**（README 边界：需真实账号与平台风控验证，发布保持 dry-run，校验逻辑全真）；数据回收（M5） |
| 依据 | `prd/PRD-Atelier-v1.0.md` §10 · `specs/SPEC-00` §3 M4 · `specs/SPEC-06` §5（平台注册规则） |

## 0. 已确认决策

| # | 决策 |
|---|---|
| D1 | **4 个新平台按 SPEC-06 §5 规则注册**：各新增 `platforms/<name>.py`（子类 BaseAdapter，只写平台差异）+ `__init__.py` ADAPTERS 各一行；`adapt.py` 的 `PLATFORM_LIMITS`/`PLATFORM_ORDER`/`_TONE` **只追加不修改**既有 3 平台条目（M4 的纲领就是扩平台，SPEC-06 §2 冻结表按批次扩展，随批登记） |
| D2 | 新平台参数按 PRD §10.4 平台矩阵与公开限制设定（工程合理值，页面上如实标注「按公开资料设定」）：快手 `ks`（图文+视频，标题 20/正文 1000）、知乎 `zhihu`（回答为主 text 形态，标题 100/正文 20000）、B站 `bilibili`（仅视频，标题 80/正文 2000，必须挂视频）、视频号 `wcs`（仅视频，标题 16/正文 1000） |
| D3 | **定时发布是调度器不是承诺**：`publish/scheduler.py` 后台协程（默认 30s 一拍，`ATELIER_SCHEDULER=0` 可关）扫 `publish_drafts.scheduled_date` 到期且尚无成功发布记录的草稿 → 走既有 `dispatcher.publish_draft`（dry-run 语义不变，记录照写 `publish_records`）；`GET /api/publish/scheduler` 给状态。**dry-run 诚实声明照带**：到点发布目前仍是模拟发出 |
| D4 | **短链是本地工具**：`shortlinks` 表（schema v7：code/target/note/hits/created_at）+ `POST/GET /api/shortlinks` + 根路径 `GET /s/{code}` 302 跳转并计数。不假装是外链短域；发布 dry-run 的模拟 URL 不自动生链（生成是显式动作） |
| D5 | **F-G19 平台优化建议**挂发布域：`POST /api/publish/optimize`（platform/title/body/profile_id）→ AI 严格 JSON `{titles[1..3], tags[1..6], timing, notes[1..3]}`，复用 `topics.service` 原语（domain="publish"），门禁后返回、不落库 |
| D6 | **账号中心（accounts 转正）诚实形态**：凭证登录（F-G25）真做——密钥经 `skills.keys` 加密存储、`platform_creds` 记状态；登录态**真校验**（F-G24）= 读 `platform_creds.state` + 更新 `verified_at`（BaseAdapter.check_auth 既有语义），并如实标注「本地凭证校验，真实有效性以发布时平台反馈为准」；**扫码登录（F-G23）诚实不可用**——需要本机浏览器自动化与真实账号环境，端点返回固定 notice 的 422，不假装弹码；登录态缓存（F-G27）= `check_auth` 结果 60s 内存缓存（force 绕过）；窗口聚焦刷新（F-G28）= 前端 visibilitychange 重拉 |
| D7 | schema v6 → v7：仅新增 `shortlinks` 表；`platform_creds` 复用既有表 |

## 1. API 契约

### 1.1 账号中心（新 `api/accounts.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/accounts` | 7 平台卡片：adapter 元数据（名称/形态/上限）+ `check_auth()` 状态（带 60s 缓存，`?force=1` 绕过） |
| POST | `/accounts/{platform}/credential` | `{account?, secret*}`：secret 经 `keys.set_secret("PLATFORM_CRED_<p>")` 加密落库，`platform_creds` upsert（state=unknown，等 verify） |
| POST | `/accounts/{platform}/verify` | 真校验：有凭证且格式合法 → state=valid + verified_at；无凭证 → 422；message 如实标注「本地校验」 |
| DELETE | `/accounts/{platform}` | 登出（F-G26）：删 `platform_creds` 行 + 删加密密钥；404 当无记录 |
| POST | `/accounts/{platform}/qr-login` | **固定 422** `{notice}`：扫码需真实账号环境（风控），当前支持凭证登录 |

未知平台 → 404。secret 永不回传（掩码）。

### 1.2 发布增强（扩 `api/publish.py` + 新 `publish/scheduler.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/publish/optimize` | F-G19（D5） |
| GET | `/publish/scheduler` | `{enabled, interval_seconds, due_count, last_tick, notice}` |
| POST | `/api/shortlinks` `{target*, note?}` | 生码（201）：code 8 位 [a-z0-9]；target 必须 http(s) |
| GET | `/api/shortlinks` | 列表（含 hits），created_at 倒序 |
| GET | `/s/{code}` | 302 → target，hits+1；不存在 404（根路径路由，在 `main.py` 挂，`/s` 不经 `/api` 前缀与跨站写中间件约束——只读跳转） |

### 1.3 调度器语义

`run_due(now)`：`scheduled_date != '' AND scheduled_date <= now` 且该草稿无 `status='sent'` 记录 → 逐个 `dispatcher.publish_draft(confirm=True, dry_run=True)`（调度触发即视为用户此前已确认过排期），结果写 `publish_records`；失败留痕不中断其余。单拍内草稿按 `scheduled_date` 升序，最多 10 个/拍。

## 2. 前端

- **accounts 页转正**：7 平台卡（名称/形态 Chip/上限/登录态色标+文案/verified_at）→ 「录入凭证」弹层（账号 + 密钥掩码回显、留空不覆盖）·「验证」·「登出」（ConfirmDialog）·固定 notice「扫码登录需真实账号环境，当前支持凭证登录」；`visibilitychange` 聚焦自动重拉（F-G28）；删除 `M2Placeholder` 依赖
- **发布中心**：PageHead 加 scheduler 状态 Chip（启用/停用 + 到期数）；草稿卡操作区加「优化建议」（弹层同构，结果分标题/话题/时机/注意四组，每个标题可一键替换草稿标题）；发布弹层已有平台选择自动含新平台（读 `/publish/platforms`）

## 3. 验收标准

1. 4 新平台出现在 `/api/publish/platforms` 与账号中心；B站/视频号挂视频才可发（否则明确报错）
2. 录入凭证 → verify → 登录态 valid 且 verified_at 更新；登出后 check_auth 未登录；secret 全程掩码
3. 排期到期的草稿被调度器 dry-run 发布并写 publish_records；未到期/已发的不再跑；`ATELIER_SCHEDULER=0` 时调度器不启动且状态端点如实报停用
4. 短链：生码 → 302 跳转 → hits 递增；未知 code 404
5. 优化建议：AI JSON 契约校验（越界 502）、门禁 BLOCK 422、不落库
6. 扫码端点诚实 422，页面如实展示能力边界

## 4. 必测清单（`atelier/tests/test_m4_platform.py`）

- 迁移 v6→v7（shortlinks 出现）；4 adapter：B站/视频号无视频 → `*_form_rejected`；知乎长文通过、快手缺封面放行（needs_cover=False）；`PLATFORM_LIMITS` 含 7 平台且旧 3 条目未被改
- 短链：CRUD + 302 + hits + 404 + target 必须 http(s)
- 调度器：种 2 个到期 + 1 个未到期 + 1 个已 sent → 只跑到期未发的；记录入 publish_records；disabled 时 run_due 直接返回 skipped
- optimize：JSON 契约 + 越界 502 + session 前缀 `publish-optimize-` + BLOCK
- accounts：列表 7 平台；credential 留空不覆盖（unchanged）；verify 无凭证 422、有凭证 valid；登出 404/200；qr-login 422 固定 notice；未知平台 404
- 前端 `accounts.test.tsx`：平台卡渲染 / 凭证弹层请求体 / 登出确认 / 聚焦刷新

## 5. 偏差与待办登记

- SPEC-06 §2「冻结的 3 平台约束表」按 D1 扩展为 7 平台（只追加）；真实发布仍 dry-run（README 边界，M4 无真实账号环境无法端到端验证）
- F-G23 扫码与 F-G16 短信墙的**真实流程**依赖平台风控验证，保持 M1 已声明的接口骨架 + 明确不可用提示；`sms_wall` 标记在新平台按 PRD 矩阵预设（抖音/B站为视频平台风险高，快手/知乎/视频号=False）
- 短链无公网域，`/s/{code}` 仅本地可用——追踪语义在本地闭环（hits），如需公网追踪待部署形态决策
