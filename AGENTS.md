# AGENTS.md · Atelier 工作区须知

面向社交媒体创作者的**私有内容工作台**：账号画像驱动 → 对话/技能产出 → 门禁校验 → 内容库归档 → 多平台发布。单用户、仅本地运行（127.0.0.1）、文件系统是产物唯一真相源。整个仓库（文档、注释、报错文案）以中文为主。

## 目录地图

```
atelier/                 唯一的 Python 包（flat-layout，见 pyproject 的 include 守卫）
  server/paths.py        ★ 路径唯一收口（铁律）
  server/harness/        Harness 抽象 + ClaudeSDKHarness + 门禁 MCP tools
  server/gates/          硬门禁/软提醒插件注册表（5 个内置：ai_flavor/compliance/secret_scan/wordcount/visual_qc）
  server/skills/         SKILL.md 加载器 + 就地运行器 + capabilities.toml 能力地图清单
  server/topics|calendar|insights|discovery|attribution/   选题/日历/分析/发现/归因 功能域
  server/publish/        平台抽象 platforms/（7 平台）+ 适配/预检/编排/调度器
  server/{profile,sessions,library,visual,media,shortlinks}/   其余功能域与共享库
  server/api/            FastAPI 路由（按域拆分，_autoload_routers 自动挂载，新增域不改 main.py）
  server/core/           db(SQLite, schema v8) / models / errors
  skills/                技能资产（49 个；每个一目录 + SKILL.md，run.py=本地确定性 或 纯 agent 手册）
  cli/main.py            CLI 入口（web/chat/skill/doctor/ping/gateway）
  tests/                 pytest（914 个）
web/                     React 18 + TS + Vite 前端（pnpm，零 UI 框架）
specs/ plans/ prd/ design/ docs/   先 spec 再 plan 再实现的文档链（SPEC-00 ~ SPEC-15）
outputs/ profiles/ var/  运行期数据，gitignore，永不入库
scripts/                 smoke_m1.py 等端到端脚本
```

## 常用命令

```bash
# 工具链路径：uv 在 ~/.local/bin，node/pnpm 在 ~/.local/nodejs/bin（都不在默认 PATH）
export PATH="$HOME/.local/bin:$HOME/.local/nodejs/bin:$PATH"

# 后端（uv + Python 3.12；dev 依赖在 dependency-groups，.[dev] 装不到）
uv pip install -e . --group dev
.venv/bin/python -m pytest -q                      # 全量后端测试（当前 914 个）
.venv/bin/python -m pytest atelier/tests/test_gates.py -q   # 聚焦单个文件
.venv/bin/python -m ruff check atelier             # lint（line-length 110, target py310）

# 前端（web/ 下，pnpm）
cd web && pnpm install
pnpm typecheck       # tsc --noEmit
pnpm test            # vitest run（当前 172 个）
pnpm build           # typecheck + vite build（后端 serve 的就是 web/dist）

# 起服务（无 API key 用 MockHarness 也能跑全链路）
ATELIER_MOCK=1 .venv/bin/python -m atelier.cli.main web   # → http://127.0.0.1:8000
.venv/bin/python -m atelier.cli.main doctor                # 环境体检（18 项）
.venv/bin/python scripts/smoke_m1.py                       # 端到端冒烟（26 项，ATELIER_MOCK=1）
```

## 架构铁律（改代码前必读）

1. **路径收口**：全项目只有 `atelier/server/paths.py` 可以拼路径。业务代码禁止 `os.path.join(ROOT, ...)` / f-string 拼路径，只能 import 常量（`OUTPUTS`/`VAR`/...）或调该文件的函数。`resolve_inside` 防 `..` 穿越和 symlink 逃逸，所有外部传入的相对路径必须过它。
2. **Harness 抽象**：业务层只认 `TurnEvent`/`TurnRequest`（`harness/base.py`），不得出现任何 `claude_agent_sdk` 类型——SDK 类型只允许存在于 `harness/claude_sdk.py`。无 `ANTHROPIC_API_KEY` 时用 `MockHarness`（`ATELIER_MOCK=1`）。
3. **门禁是代码路径事实**：AI 产出落盘前必须过 in-process MCP tool（`atelier_gate_run` / `atelier_artifact_write`，见 `harness/tools.py`）。硬门禁 BLOCK 直接报错附改法；软提醒不阻断。不是提示词约定，不许绕过。
4. **元数据与产物分离**：产物落 `outputs/<项目>/{成品,素材}/`；会话/消息/发布记录等元数据落 SQLite `var/atelier.db`；每轮原始记录落 `var/sessions/<sid>/<turn_id>.jsonl`。
5. **安全基线**：服务只监听 127.0.0.1；CORS 默认只放本地来源；写请求有跨站拦截（`application/x-www-form-urlencoded` 被刻意拒绝）；密钥只读不回传（`config.py` 的 `redacted()` 掩码）。不得放宽这些默认。
6. **配置只从环境变量读**（`server/config.py`），不引入配置文件。常用：`ATELIER_ROOT`、`ATELIER_MOCK`、`ATELIER_DISABLE_CSRF`（仅测试）、`ATELIER_SCHEDULER=0`（关定时发布调度器）。
7. **新能力走注册表 + 同步计数断言**（这是最容易漏的一步，漏了全量测试会红）：
   - 新技能 → 加 `skills/<id>/`（SKILL.md 必填 10 字段，id=目录名）+ 登记进 `server/skills/capabilities.toml`；同步 `test_skills.py`（技能总数 49、需密钥/付费集合）
   - 新门禁 → 加 `gates/<name>.py` 并 `@register`，把模块名追加进 `gates/registry.py` 的 `BUILTIN_MODULES`；同步 `test_gates.py` / `test_main.py` / `test_tools.py` 的「5 个门禁」计数
   - 新发布平台 → 只加 `publish/platforms/<name>.py` + `__init__.py` ADAPTERS 一行 + `adapt.py` 的 `PLATFORM_LIMITS`/`PLATFORM_ORDER`/`_TONE` **只追加**；同步 `test_publish.py`（7 平台）与 `core/models.py` 的 `PlatformVariant` Literal
   - schema 新版本 → `core/db.py` 加 `_apply_vN`（当前 v8）+ `TABLE_NAMES`/`_EXPECTED`/`_MIGRATIONS` 只追加；同步 `test_db.py`（EXPECTED_TABLES、版本号）与 `test_skill_runs.py`（表总数）
   - 付费技能 → 在 `skills/runner.py` 的 `COST_RATES` 登记单价（付费必须先给费用预估）
   - doctor 检查项 → 同步 `test_doctor.py` 的项数断言（当前 18）

## 前端约定（web/）

- **零 UI 框架**：不用 tailwind / 组件库。设计令牌是原生 CSS 变量，视觉唯一依据是 `design/UI-SPEC.md` + `design/prototype-v1.html`，不自行发挥。
- 单主色 `--accent #10b981`；语义色只用于状态不做装饰；禁止纯黑/紫蓝渐变/霓虹；一屏一个 primary 按钮；破坏性操作必须二次确认。
- `src/lib/api.ts` 是唯一 API client：非 2xx 抛 `ApiError` 并自动 toast（调用方自行处理时传 `handled: true`）。后端错误体统一为 `{error:{code,message,detail,hint}}`。
- 路径别名 `@` → `web/src`（vite + tsconfig 已配）。dev server :5173 代理 `/api` → :8000。
- 页面按 feature 目录组织（`src/features/<域>/`），基础组件在 `src/components/`。

## 已知坑

- **flat-layout 打包**：`pyproject.toml` 显式 `include = ["atelier*"]`。新增顶层目录（非 `atelier` 开头）会让 setuptools 拒绝构建。
- **ROOT 探测**：运行时根 = `ATELIER_ROOT` > 向上找仓库标记 > cwd 上一级。测试里用 `paths.configure(tmp_path)` 重绑根，别假设 cwd。
- **冻结接口**：SPEC 各节标了「冻结」的函数名/契约（如 SPEC-01 §11 冻结 paths.py 函数名）不能随手改；要改先提 spec 变更。
- **发布是 dry-run**：校验逻辑全真、发送模拟——真实发布与扫码登录需真实账号与平台风控验证，M4 也没突破；定时发布调度器到点触发的是同一套流程（`publish/scheduler.py`），发出环节同样模拟并带 dry_run 标记。不要假装能真发。
- **诚实模式**：数据不足时返回 `{insufficient: true, need, message}` 且**不调模型**（测试断言 `fake.requests == []`）；AI 只解读代码算出的统计，不许编数字。平台表现数据无公开 API，靠手工录入（归因域）。
- **AI 任务契约**：域内 AI 调用一律走 `topics/service.py` 的原语（`run_ai_text(domain=...)` / `extract_json` / `gates_block_or_raise`）；模型输出缺段/越界抛域错误（422/502），不截断救场、不硬编补齐。
- **pytest asyncio_mode = auto**：异步测试不用手动标 `@pytest.mark.asyncio`。
- **测试夹具**：`conftest.py` 的 `atelier_root`（临时根）+ `fake`（ScriptedHarness 按队列吐文本）；没有 `atelier_root` 的测试不允许存在。
- **项目名正则**：`^[a-z0-9][a-z0-9-_]{0,63}$`（全小写）；系统文件 `.session/`、`.index.json`、`.atelier*` 禁止删除。
- 提交信息用 conventional 前缀 + 中文描述（如 `feat: Atelier M0 地基 + M1 纵向闭环`）。

## 改敏感区前先读

| 要改的地方 | 先读 |
|---|---|
| 路径 / 存储 / 安全 / harness | `specs/SPEC-00-overview.md` + `specs/SPEC-01-foundation.md` |
| 选题 / 日历 / 排期 / 分析 / 发现 / 制作 / 平台 / 归因 | 对应 `specs/SPEC-08 ~ SPEC-15`（每个域的 API 契约、冻结段、偏差登记都在里面） |
| 某功能域（画像/对话/技能/内容库/发布/前端） | 对应 `specs/SPEC-02 ~ SPEC-07` |
| 前端视觉与交互 | `design/UI-SPEC.md`（25 条交互规则） |
| 任务拆解与文件归属 | `plans/PLAN-M0-M1.md`、`plans/PLAN-M2.md` |
| 当前能力边界与验收状态 | `docs/ACCEPTANCE-M1.md`、`docs/ACCEPTANCE-M2-M5.md` |

产品全量需求在 `prd/PRD-Atelier-v1.0.md`；明确不做的事（多租户、移动端、内容审核仲裁等）见 README「边界」。
