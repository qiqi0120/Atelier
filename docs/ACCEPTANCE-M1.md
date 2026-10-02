# M1 验收报告 · Atelier

| 项 | 值 |
|---|---|
| 日期 | 2026-10-02 |
| 批次 | **M0 地基 + M1 纵向闭环** |
| 依据 | `specs/SPEC-00` §3 的 M1 出口标准、`specs/SPEC-01~07` |
| 结论 | **M1 出口标准 8 条全部通过**，26/26 端到端断言通过 |

---

## 1. 交付概览

| 域 | 功能点 | 后端 | 前端 |
|---|---|---|---|
| 地基（M0） | paths / harness / 门禁 / SQLite / CLI / doctor | 11 模块 | 设计系统 17 组件 |
| A 账号画像 | F-A1/2/4/5/6 | `profile/` + 14 端点 | 8 组件 |
| B 对话工作台 | F-B1~B8 | `sessions/` + 12 端点 | 11 组件 + SSE 客户端 |
| C 能力地图/技能库 | F-C1~C4、C6~C10 | `skills/` + 12 技能 | 能力卡 + 技能抽屉 |
| G 内容库 | F-G1~G8 | `library/` + 11 端点 | 7 组件 |
| G 发布中心 | F-G9~G18 | `publish/` + 3 平台适配器 | 10 组件 |

**测试总量**：后端 **671 passed** · 前端 **92 passed** · `ruff check .` All checks passed · `pnpm build` ✓ 1.14s · 字面色值 0 处

---

## 2. M1 出口 8 条逐条验收

| # | 出口标准 | 结果 | 实测证据 |
|---|---|---|---|
| 1 | 建画像 → 切画像后下一轮产出风格可见变化 | ✅ | 两画像 `system_prompt` 互不包含；通用模式 `injected=false`、`leaked_dims=[]` |
| 2 | 对话断网重连，AI 已生成内容不丢失 | ✅ | `GET /turn/{id}` 取回 11 事件，`index` 连续，含 `text_delta`+`done` |
| 3 | 停止生成 2s 内生效 | ✅ | 实测 **0.138s**（cancel 优先，0.6s 宽限后兜底补 done） |
| 4 | 点能力只填入不发送 | ✅ | 真机点「小红书知识卡」→ 跳对话页 + 填入 + toast，消息区无新增 |
| 5 | 未配置密钥的技能明确告知缺什么、运行禁用 | ✅ | `one-video` → **409**；UI 标 `!` 角标 + 运行按钮禁用 |
| 6 | 产物落 `outputs/<项目>/成品`，路径可点击直达 | ✅ | 技能产出 3 个文件，内容库项目树可见 |
| 7 | 母版 → 多平台版本，字数超限红标并阻断发布 | ✅ | 62/55 `over=True` → 预检 `blocked=true`，未 confirm 拒绝发布 |
| 8 | 发布有二次确认，失败给明确原因 | ✅ | 二次确认弹窗列出平台形态与登录态；错误码映射人话 |

---

## 3. 端到端冒烟（26/26）

`scripts/smoke_m1.py` — 真服务 + 真实 HTTP，不是 mock。

```
【出口 1】画像       4/4   建画像·切换注入变化·通用模式·不落全局文件
【出口 2】对话       4/4   SSE 流式·独立思考流·断线恢复·0.138s 中断
【出口 3】能力/技能  4/4   4 组 14 项·触发语成熟度齐全·12 技能·v2/v3 标记
【出口 4】门禁       2/2   硬门禁命中阻断（医疗功效）·密钥只回掩码
【出口 5】技能→库    3/3   跑通产 3 产物·付费技能 409·内容库可见
【出口 6】内容库     4/4   Range 206·逃逸 400·confirm token·错 token 422
【出口 7】发布       5/5   62/55 硬阻断·BLOCK/WARN 分级·裁剪 44/55·未 confirm 拒绝
```

### 分级语义验证（F-G13 硬要求）

```
block  ✓过    合规风险扫描
block  ✗未过  小红书正文超字数（硬门禁）
block  ✗未过  小红书封面图
block  ✗未过  小红书登录态真校验
block  ✓过    出站密钥扫描
warn   ✓过    标题打分
warn   ✓过    人设一致性（软提醒，不阻断）   ← 确认不阻断
warn   ✗未过  时机建议
```

---

## 4. 真实浏览器验收

起真服务（`ATELIER_MOCK=1`），逐页访问确认：

| 页面 | 状态 | 备注 |
|---|---|---|
| `/` 工作台 | ✅ | 概览卡/待办/快捷入口/热榜速览齐全 |
| `/chat` 对话 | ✅ | 会话列表 + 消息流 + 门禁块 + 问答题卡片；SSE 实跑 |
| `/capability` 能力地图 | ✅ | 4 组 14 项接真数据，成熟度四态可见 |
| `/library` 内容库 | ✅ | **生成的 1080×1440 卡片真图渲染**，系统目录带「系统」标记 |
| `/publish` 发布中心 | ✅ | 空态规范（每处都给了下一步动作），平台约束齐全 |
| 13 个路由 | ✅ 全部 200 | SPA 深链不 404 |
| 控制台 | ✅ 0 error | |
| 375px 窄屏 | ✅ 无横向滚动 | device emulation 实测 |

---

## 5. 集成阶段修复的真 bug

并行开发的代价是跨域不一致，以下都是**集成时才发现**的：

| # | 问题 | 影响 | 修法 |
|---|---|---|---|
| 1 | **门禁与预检两套字数口径** | 同一段文字门禁显示 36、预检 29；英文标题差 4.8 倍，门禁会把 20 词英文标题误判超限而**错误阻断** | 计数原语下沉到 `gates/wordcount.py`，发布域经模块转发复用 |
| 2 | `from X import f` 在 gates reload 后绑死旧函数 | 运行期 `registry.clear()` 会让发布域静默用过期实现 | 改为经模块引用，实测 reload 后自动跟随 |
| 3 | **SPA 深链全 404** | 13 个路由直接刷新全挂 | `StaticFiles` 子类化 + SPA fallback |
| 4 | SPA 兜底过宽 | 缺失图片返回 HTML，浏览器报一堆解析错 | 按 `Accept` 头区分导航与子资源 |
| 5 | **CSRF 中间件误伤无 body 的 DELETE** | `curl -X DELETE` 莫名 403 | 只有 POST 需要强制 JSON（表单只能发 GET/POST），8 个攻击向量仍全拦 |
| 6 | 技能异步 `run_id` 对不上 | 客户端永远查不到运行记录（`status: unknown`） | 用端点 run_id 入表 |
| 7 | PATCH 要求客户端补派生字段 | 「改一下标题」这种最常见编辑会 422 | 服务端补默认并 recount |
| 8 | 消息头显示原始 `t_8c12dc73b…` | 调试信息泄漏到界面 | 改显示时间戳，turn_id 降为 hover |
| 9 | 「发布到 0 个平台」可点 | 空态误导 | 0 个平台时禁用 + 说明原因 |
| 10 | CJK 避头尾违规 | 卡片第三行以「。」开头 | 追い込み策略，标点不落行首 |
| 11 | 裁剪过度保守 | 62 字裁到 55 只剩 21，白扔 34 字预算 | 边界仅在预算后段（≥60%）时采纳 |

---

## 6. 已知缺口（不掩饰）

| 缺口 | 原因 | 归属 |
|---|---|---|
| **真实发布**为 dry-run | 需真实账号 + 平台风控验证 | M4（接口完整、行为可替换、响应带 `dry_run:true`，`dry_run=False` 时显式返回 `not_implemented` 而非假装成功） |
| **扫码登录**未做 | 同上 | M4（`platform_creds` 表与真校验接口已建） |
| 短信验证码 | 只到状态机 + UI | M4 |
| 排期发布 | `adapter.schedule` 已留签名 | M4 |
| 热点抓取 / 选题库 / 日历 / 数据复盘 | 属 M2 | 路由已注册、占位页就位，切分见 `plans/PLAN-M2.md` |
| 视频/音频生成 | 属 M3 | `one-video`/`aigc-image` 标 v2 并演示缺密钥禁用 |
| ~~技能运行记录在进程内~~ | **已还**（2026-10-02） | 落 `skill_runs` 表，schema v2，详见 §9 |
| `cover_ratio` 按文件名判定 | 未读图片二进制 | 需内容库域协作 |
| 真实 SDK 未跑通 | **仍欠**，见 §9 | 验证脚本已就绪，等真 `ANTHROPIC_API_KEY` |

---

## 7. 复现方式

```bash
# 环境（已就绪）
uv venv --python 3.12 && uv pip install -e . --group dev
cd web && pnpm install

# 全量测试
.venv/bin/python -m pytest -q          # 671 passed
cd web && pnpm test && pnpm build      # 92 passed

# 起服务（无 API key 也能跑通全链路）
ATELIER_MOCK=1 .venv/bin/python -m atelier.cli.main web

# 端到端冒烟
ATELIER_MOCK=1 .venv/bin/python scripts/smoke_m1.py

# 环境体检
.venv/bin/python -m atelier.cli.main doctor
```

---

## 8. 下一批建议（M2）

按 `SPEC-00` §3 的批次规则，M1 出口达标即可开 M2（策划与发现增强）。

**切分方案见 `plans/PLAN-M2.md`**（Mr Yu 2026-10-02 选定「按链路切 3 个子批」：
①选题 → ②日历与热点 → ③发现与分析），本轮不执行。

开批前建议先做两件小事：

1. ~~把技能运行记录落库（`runs` 表）~~ —— ✅ 已完成，见 §9
2. ~~补一个真 API key 跑一次真实 Claude Agent SDK 对话~~ —— ⏳ 验证脚本就绪，等 key，见 §9

---

## 9. M1 收尾轮（2026-10-02）

### 9.1 欠账① 技能运行记录落库 —— 已还

| 项 | 内容 |
|---|---|
| 落点 | `skill_runs` 表（`core/db.py` schema **v1 → v2**），spec 已先改（SPEC-01 §7） |
| 存储层 | 新增 `atelier/server/skills/store.py`：`start_run` / `finish_run` / `get_run` / `list_runs` |
| API | `GET /api/skills/runs/{id}` 内存未命中时回库查；新增 `GET /api/skills/runs` 历史列表（按技能/项目/状态过滤） |
| 设计 | 写穿缓存 + 库为唯一真相源；**落库失败不拖垮运行**（产物已落盘），但 `log.exception` 大声留痕 |
| 测试 | 新增 `atelier/tests/test_skill_runs.py` **12 个用例**，含 v1→v2 真实迁移路径 |
| 总测试 | **684 passed**（671 + 13）· `ruff check .` All checks passed · `doctor` 报 `schema v2 · 10/10 张表` |

**实证（真服务进程 kill -9 后重启）**：

```
跑 xhs-card → run_id=ddc5cb70… status=done 产物=4
kill -9 → 重启 → GET 同一条：status=done 产物=4 created_at 2026-10-02T09:43:43 门禁报告=有
GET /api/skills/runs?skill_id=xhs-card → 命中 1 条
```

### 9.2 收尾轮修的真 bug

| # | 问题 | 影响 | 修法 |
|---|---|---|---|
| 1 | **`uv pip install -e ".[dev]"` 从来跑不通** | 验收报告 §7 的复现命令是坏的：flat-layout 下 setuptools 扫到 `web/prd/plans/specs/design` 六个顶层包直接拒绝构建 | `pyproject.toml` 显式 `[tool.setuptools.packages.find] include=["atelier*"]`；复现命令改 `uv pip install -e . --group dev`（dev 在 `dependency-groups` 里，`.[dev]` 装不到） |
| 2 | **`wait=True` 每次同步运行产生 2 条记录** | 入口 `run_id` 与 `runner` 内部自生成的 `run_id` 是两个值，`start_run` 写一行、`finish_run` 又写一行 | 同步分支补 `r.run_id = run_id`，与异步分支同口径（同 M1 集成 bug #6 的同类） |
| 3 | **`ThinkingConfigAdaptive()` 返回空 dict `{}`** | 它是 TypedDict（类型）不是类。SDK 读 `t["type"]` → `KeyError`，**每条真实对话 connect 即崩** | 改字典字面量 `{"type": "adaptive"}`；兼容判据改为看 `ClaudeAgentOptions` 有无 `thinking` 字段 |
| 4 | **`async for x in asyncio.wait_for(gen, t)`** | `wait_for` 返回协程不是异步迭代器 → `TypeError`，**每条真实对话第一轮即崩** | 换 `_aiter_with_total_timeout()`，保持「整轮总超时」语义，只用 3.10 API |
| 5 | **`client.interrupt()` 是 async，代码当同步调** | 协程从未 await → SDK 侧中断**从未发生**，静默退化成「只置 stop 标记 + 0.5s 后 cancel」，实测 7.5s 才停（**出口标准 3 的直接死因**） | 按 `inspect.isawaitable()` 兼容处理，async 则 await。**实测 7.5s → 2.51s** |
| 6 | **`UserMessage` 被整个丢弃，工具结果全丢** | SDK 把 `ToolResultBlock` 装在 `UserMessage` 里回传，而映射函数对 `UserMessage` 直接 `return out` → 前端只收得到 TOOL_CALL、永远等不到 TOOL_RESULT，门禁块一直转圈。**真机实测：调了 3 次门禁 tool，收到 0 条 tool_result** | `UserMessage` 分支单独解析 `ToolResultBlock` |
| 7 | **同源写请求全被 403（打包自部署不可用）** | `cors_origins` 默认只有 Vite dev server 的 :5173。`atelier web` 自己 serve 构建好的 SPA 时，页面与 API **同源**（:7300），所有写请求都撞白名单 → **对话发不出去、技能跑不了、画像存不进去**。M1 验收时全程走 `pnpm dev`（:5173），这条路径从未被验证 | ① `CrossSiteWriteMiddleware._is_same_origin()`：Origin 与请求自身 `host:port` 相同即同源放行（不含跨站风险，且 `Sec-Fetch-Site` 本就是 `same-origin`）；② `Settings.effective_cors_origins()` 收敛成**单一来源**，CORS / 跨站写 / `/api/health` / doctor 都读它；③ `launch_web` 把 CLI 的 `--host/--port` 同步回 settings（原先 `/api/health` 一直报 8000） |
| 8 | **正文完整出现两次** | 开了 `include_partial_messages=True` 后，SDK **先**逐 token 发 `StreamEvent`，末尾再用一条 `AssistantMessage` 把同一份正文/思考**整块重发**。两个源都映射 → 每段话在界面上出现两遍。**真机实测：短增量累计 154 字，随后又来 32 + 122 = 154 字** | `events_from_message(..., streamed=)` 标记；本轮已收到增量时跳过重复的 Text/Thinking 块，**`ToolUseBlock` 保留**（工具入参没有 StreamEvent 对应物） |

> **8 个 bug 里有 6 个（3/4/5/6/7/8）藏在 M1 从未真实验证过的路径上**——
> 前 5 个在真 harness 执行路径（被 MockHarness 完全绕开），#7 在打包自部署路径
> （被 Vite dev server 完全绕开）。M1 的 671 个测试全绿，
> 但**没有任何一个测试让 SDK 真正构造过一次命令行、处理过一条真实形状的
> `UserMessage`、以「后端自己 serve 前端」的形态发过一次写请求，
> 或处理过「增量 + 整块重发」这种双源序列**。
>
> 已补四道防线：
> - `test_thinking_config_survives_sdk_command_builder` 直接调用 SDK 自己的 `_build_command()`
> - `test_tool_result_in_user_message_is_not_dropped` 用 **UserMessage 真实形状**构造消息
> - `test_own_origin_write_allowed` / `test_same_host_other_port_still_blocked` 锁死同源判定
> - `test_assistant_text_not_duplicated_when_streamed` 锁死去重
>
> 旧用例 `test_tool_use_and_result` 把 `ToolResultBlock` 塞进 `AssistantMessage`——
> 那不是 SDK 真实产生的形状，正是 bug #6 活下来的原因。

### 9.3 欠账② 真实 SDK 验证 —— 管道层已验实，Claude 专有行为未验

**凭证说明（重要）**：本机 `~/.claude/settings.json` 里**不是官方 Anthropic key**，
而是智谱 GLM 的 Anthropic 兼容端点（`open.bigmodel.cn/api/anthropic`，模型 `glm-5.3-flash`）。
因此下表结论限定为「**对着 Anthropic 兼容端点验证管道层**」，
**不等于**「真实 Claude 已跑通」，措辞不得含糊。

跑法：`export ANTHROPIC_API_KEY=… && .venv/bin/python scripts/verify_real_sdk.py`（支持 `--only c5 c6`）。
已确认：bundled CLI 是自包含 Mach-O arm64 二进制（225MB），**不需要 Node.js**。

| # | 检查 | 结果 | 实测 |
|---|---|---|---|
| 1 | health() 认证 | ✅ | `claude_sdk · harness 就绪`，5 个 MCP tool 已注册 |
| 2 | 错误密钥报错 | ⚠️ 不适用 | 父环境有 `ANTHROPIC_AUTH_TOKEN`，代理优先用它，注入的坏 key 送不出去（**测试装置限制，非代码问题**） |
| 3 | 真流式增量 | ✅ | **228 个 text_delta / 81.4s / 正文 772 字**，真实花费 $0.183 |
| 4 | 独立思考流 | ✅ | `thinking_start=1` `thinking_delta=711` |
| 5 | **门禁 tool 真被模型调用** | ✅ | `atelier_gate_run`×1 + `atelier_artifact_write`×3，**4 条 tool_result**（修复前 0 条） |
| 6 | 中断 2s 内生效 | ✅ | 发起 2.50s → 实际停 **2.51s**（修复前 7.5s） |
| 7 | 多轮续接 | ✅ | 第二轮答出「紫罗兰七号」，`resume` 生效 |
| 8 | 画像注入 | ✅ | 回答明显带画像语气与受众设定 |

**第 5 条是 M0 的核心主张**（门禁做成 in-process MCP tool，agent 落盘前**必须**调用，
不是提示词约定）——这是它第一次在真模型上被证伪不了。

### 9.4 顺带查出的门禁合规缺口（**未修，待决策**）

验证中让模型写含「国家级」「最有效」的文案，门禁**没有拦**。查证后确认：

| 输入 | 拦截 | 说明 |
|---|---|---|
| 「全网第一 / 100%有效」 | ✅ | 词表内 |
| 「三天根治 / 药到病除」 | ✅ | 医疗功效表 |
| 「我最好的朋友推荐」 | ✅ 正确放过 | 歧义表达，刻意走 `_PATTERNS` 避免误杀 |
| 「全网最好用」 | ✅ | 上下文正则生效 |
| **「国家级 / 最高级 / 最有效」** | ❌ **漏** | 见下 |

门禁**逻辑本身是好的**，缺的是词表覆盖：`国家级`/`最高级` 属《广告法》第九条
**无条件禁止**的用语（零歧义，加进硬表不会误杀）；`最有效` 有歧义，
应走 `_PATTERNS` 的上下文规则而不是硬表。

> 为什么 M1 没发现：验收脚本里没有一条断言覆盖这三个词，且 M1 从未用真模型产出过
> 含此类用语的文案去撞门禁。**本轮未擅自改动词表**——BLOCK 级门禁加词会直接
> 增加误杀面，属产品决策，需 Mr Yu 确认。
