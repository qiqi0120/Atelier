# PLAN · M0 地基 + M1 纵向闭环

| 项 | 值 |
|---|---|
| 日期 | 2026-10-02 |
| 输入 | `specs/SPEC-00` ~ `SPEC-07`、`design/UI-SPEC.md` |
| 出口 | `SPEC-00` §3 的 M1 出口标准 8 条 |

---

## 1. 依赖图

```
              ┌──────────────────────────────┐
              │ W1-A 地基后端                 │
              │ paths/harness/gates/db/models │
              └───────────────┬──────────────┘
                              │ 冻结共享契约
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌──────────────────┐   ┌──────────────┐
│ W1-B 技能资产  │   │ W1-C 前端外壳     │   │ (我) Python  │
│ 12 SKILL.md   │   │ 令牌/组件/布局     │   │ 环境准备      │
│ loader+runner │   │ 占位页            │   └──────────────┘
└───────┬───────┘   └────────┬─────────┘
        │                    │
        └────────┬───────────┘
                 ▼
    ┌────────────────────────────────────────┐
    │ Wave 2（四路并行，文件互不重叠）          │
    │ A 画像  B 对话  C 内容库  D 发布中心     │
    └───────────────────┬────────────────────┘
                        ▼
              ┌───────────────────┐
              │ Wave 3 集成 + 冒烟  │
              └───────────────────┘
```

---

## 2. 文件归属表（**并行安全的核心**）

> 规则：**只写自己那一列**。需要别人的东西就 import，不许跨列改文件。

### Wave 1

| Agent | 拥有（可写） | 禁止触碰 |
|---|---|---|
| **W1-A 地基后端** | `pyproject.toml`、`atelier/__init__.py`、`atelier/server/{main,config,paths,errors}.py`、`atelier/server/core/**`、`atelier/server/harness/**`、`atelier/server/gates/**`、`atelier/cli/**`、`atelier/launcher.py` | `api/**`、`skills/**`、`profile|sessions|library|publish/**`、`web/**` |
| **W1-B 技能资产** | `atelier/skills/**`（12 个技能目录）、`atelier/server/skills/**`、`atelier/server/api/capability.py` | 其余全部 |
| **W1-C 前端外壳** | `web/**`（全部，但 `src/lib/sse.ts` 与 `src/features/{chat,library,publish,profile}/` 除外） | `atelier/**` |

### Wave 2

| Agent | 拥有（可写） | 禁止触碰 |
|---|---|---|
| **W2-A 画像** | `atelier/server/profile/**`、`atelier/server/api/profile.py`、`web/src/features/profile/**` | 其余全部 |
| **W2-B 对话** | `atelier/server/sessions/**`、`atelier/server/api/chat.py`、`web/src/features/chat/**`、`web/src/lib/sse.ts` | 其余全部 |
| **W2-C 内容库** | `atelier/server/library/**`、`atelier/server/api/library.py`、`web/src/features/library/**` | 其余全部 |
| **W2-D 发布** | `atelier/server/publish/**`、`atelier/server/api/publish.py`、`web/src/features/publish/**` | 其余全部 |

### 跨 Agent 集成点（由 W1-A 预先提供，避免后写 main.py）

```python
# atelier/server/main.py —— 自动发现
def _autoload_routers() -> None:
    """扫描 atelier/server/api/*.py，自动 include 任何模块级 `router`。
    新增域只需新建一个 api/<name>.py 并定义 router，无需改 main.py。"""
```

---

## 3. Wave 1 任务

### W1-A · 地基后端

| # | 任务 | 验收 |
|---|---|---|
| A1 | `pyproject.toml` + uv venv + 依赖安装 | `python -c "import fastapi, claude_agent_sdk"` |
| A2 | `paths.py` 全实现（SPEC-01 §1 全部函数） | `tests/test_paths.py` 8 个用例全过，含 symlink 逃逸 |
| A3 | `errors.py` 全错误码（SPEC-01 §2 表格逐条） | 每个 code 都能 `to_dict()` |
| A4 | `core/db.py` 建表（SPEC-01 §7 全部 9 张表 + 迁移） | 建库成功，FK 开启 |
| A5 | `core/models.py`（SPEC-01 §6 全部 Pydantic 模型，逐字对齐） | `python -c "from atelier.server.core import models"` |
| A6 | `harness/base.py`（`Harness` 协议 + `TurnEvent` + `EventType`） | 与 spec 签名逐字一致 |
| A7 | `harness/claude_sdk.py`：流式 + 思考流 + 中断 + 恢复 | 无 API key 时 `health()` 报 `HarnessAuthError` 而不是崩 |
| A8 | `harness/tools.py`：5 个 `@tool`（门禁不可绕过 + 落盘） | `atelier_gate_run` 命中 BLOCK 时 tool 返回 blocked |
| A9 | `gates/` 4 个门禁 + 注册表 + 分级语义 | 极限词能命中；`secret_scan` fail-closed |
| A10 | `main.py` app factory + CORS + 跨站写拦截 + 静态挂载 + 路由自动发现 | `/api/health` 200 |
| A11 | `cli/`：`web` `chat` `skill` `doctor` `ping` 五个命令 | `atelier doctor` 输出 17 项 |
| A12 | `tests/` 全部单测（至少 40 个用例） | `pytest` 全绿 |

**W1-A 不需要真实 API key 就能完成 A1–A6、A9–A12。** A7/A8 用 mock harness 测。

### W1-B · 技能资产

| # | 任务 | 验收 |
|---|---|---|
| B1 | 9 个 `maturity: v0` 技能（真能跑，纯 Python/规则实现） | 逐个 `atelier skill run <id>` 成功 |
| B2 | 3 个 `maturity: v2/v3` 技能（`one-video` `aigc-image` `music`） | 缺密钥时运行禁用 |
| B3 | `loader.py` 扫描 + front-matter 解析 + mtime 缓存 | 改 SKILL.md 后自动重扫 |
| B4 | `manifest.py` + `capabilities.toml`（4 组能力映射） | 无死链（每条 capability 都能找到 skill） |
| B5 | `runner.py` 就地运行（注入画像 + 触发语 + 产物收集 + 门禁） | 跑 `xhs-card` 在 outputs 产出文件 |
| B6 | `executor.py` 子进程沙箱（`shell=False`、超时 kill、stderr 8KB） | 故意失败的脚本返回码 + stderr 摘要 |
| B7 | `api/capability.py`（能力地图 + 技能库 + 密钥 CRUD） | 密钥只写不回传、留空不覆盖 |
| B8 | `tests/test_skills.py` 8 个用例 | 全绿 |

### W1-C · 前端外壳

| # | 任务 | 验收 |
|---|---|---|
| C1 | Vite + React 18 + TS 骨架，`pnpm install` | `pnpm build` 通过 |
| C2 | `styles/tokens.css`（UI-SPEC §2 **原样搬**）+ `global.css` | 令牌与 spec 逐值一致 |
| C3 | 18 个基础组件 | 每个至少 1 个渲染测试 |
| C4 | `lib/api.ts`（`ApiError` 统一处理）+ `store.ts` + `types.ts` | 错误自动 toast |
| C5 | `layout/`：Sidebar(236→60) + Topbar + ProfileSwitcher | 折叠正常 |
| C6 | `App.tsx` 13 路由 + 外壳布局 | 13 路由可访问无白屏 |
| C7 | 5 个占位页（hot/topics/calendar/accounts/analytics）+ 7 个 M1 域占位 | 占位页含「M2 接入」说明 + 按钮 |
| C8 | 响应式：900px 收侧栏、768px 单列、**无横向滚动** | 375px 宽截图验证 |
| C9 | 视觉比对：与 `prototype-v1.html` 逐页对照 | 截图比对通过 |

---

## 4. Wave 2 任务

| Agent | 后端 | 前端 | 测试 |
|---|---|---|---|
| **W2-A 画像** | `profile/{store,prompt,wizard}.py` + `api/profile.py`（13 个端点，SPEC-02 §5） | `features/profile/`（编辑器/向导/记忆面板/通用模式） | 8 后端 + 3 前端 |
| **W2-B 对话** | `sessions/{store,manager,sse}.py` + `api/chat.py`（SPEC-03 §3/§5） | `features/chat/`（11 个组件）+ `lib/sse.ts` | 10 后端 + 4 前端 |
| **W2-C 内容库** | `library/service.py` + `api/library.py`（11 个端点，SPEC-05 §3，**含 Range**） | `features/library/`（树/网格/预览/删除确认） | 11 后端 + 3 前端 |
| **W2-D 发布** | `publish/{adapt,precheck,wordcount,dispatcher}.py` + `platforms/*.py`（3 个）+ `api/publish.py` | `features/publish/`（8 个组件） | 12 后端 + 4 前端 |

**W2-B 是最重的一路**（断线恢复 + 中断 + 并发锁三条硬验收）。

---

## 5. Wave 3 · 集成与验收（我执行）

1. 合并检查：无 import 断裂、无循环依赖
2. `pytest` 全量 + `pnpm build` + `tsc --noEmit`
3. 跑冒烟脚本：`建画像 → 发一轮对话 → 点能力填入 → 跑技能 → 看门禁 → 查内容库 → 生成发布草稿 → 预检`
4. 逐条核对 M1 出口 8 条，输出验收报告 `docs/ACCEPTANCE-M1.md`
5. 浏览器实测关键路径并截图

---

## 6. 风险与预案

| 风险 | 预案 |
|---|---|
| Claude Agent SDK 实际 API 与文档有出入 | A7/A8 用 mock harness 先跑通；真实连通用 `ANTHROPIC_API_KEY` 最后接 |
| 无 API key 无法端到端验证对话 | harness 层提供 `MockHarness`（写死流式输出），`ATELIER_MOCK=1` 启用；**不阻塞其他域** |
| 抖音/小红书真实发布不可验证 | 已知缺口，dry-run + RUNBOOK（M4 补） |
| 11 路并行文件冲突 | 靠 §2 归属表 + 「只写自己那列」硬规则 |
| 前端视觉跑偏 | C9 强制与原型逐页比对，不通过不算完成 |

---

## 7. 不在本次范围

M2–M5 全部功能点、真实扫码登录、真实发布、视频/音频生成、热点抓取、数据归因。
**理由与批次归属见 `SPEC-00` §3。**
