# SPEC-00 · Atelier 总览与架构基线

| 项 | 值 |
|---|---|
| 版本 | v1.0 |
| 日期 | 2026-10-02 |
| 依据 | `prd/PRD-Atelier-v1.0.md`（161 功能点 / 83 个 P0）、`design/UI-SPEC.md`、`design/prototype-v1.html` |
| 审核人 | Mr Yu（已确认 Q1–Q4） |

## 0. 已确认的决策（不再讨论）

| # | 决策 | 内容 |
|---|---|---|
| D1 | AI 运行时 | **Claude Agent SDK（Python `claude-agent-sdk`）**，前置 `Harness` 抽象接口，未来可换 provider |
| D2 | 技术栈 | 后端 **Python 3.12 + FastAPI**；前端 **React 18 + TypeScript + Vite** |
| D3 | 首批范围 | **M0 地基 + M1 纵向闭环**（画像 → 对话 → 能力地图/技能库 → 内容库 → 发布中心），约 40 个 P0 |
| D4 | 平台首发 | 小红书 + 抖音 + 微信公众号（PRD Q1 建议，未反对，按此执行） |
| D5 | UI | 采用 `design/prototype-v1.html` + `design/UI-SPEC.md`，不返工 |
| D6 | 产物存储 | 文件系统为唯一真相源；元数据走 SQLite；**路径解析收口到 `paths.py`** |
| D7 | 编排组织 | **不采用单文件**，按能力域拆模块（PRD 14.1 明确否掉参考实现的做法） |

---

## 1. 系统架构

```
┌──────────────────────────────────────────────────────────┐
│  web/  React 18 + TS + Vite                              │
│  外壳(导航/路由) + 13 页 feature 目录 + 设计令牌(tokens.css)│
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP / SSE（仅 localhost）
┌────────────────────────▼─────────────────────────────────┐
│  server/  FastAPI                                         │
│  api/     按域拆路由：profile chat capability library …    │
│  core/    db(SQLite) models errors                        │
│  harness/ ★ Harness 抽象 + ClaudeSDKHarness 实现          │
│  gates/   ★ 硬门禁/软提醒 插件注册表                      │
│  skills/  SKILL.md 加载器 + 就地运行器                    │
│  publish/ 平台抽象 + 三个平台实现 + 预检                   │
└────────────────────────┬─────────────────────────────────┘
                         │ 进程内 MCP 工具（不可绕过）
┌────────────────────────▼─────────────────────────────────┐
│  Claude Agent SDK (claude-agent-sdk)                      │
│  ClaudeSDKClient 流式会话 · @tool in-process MCP server    │
└────────────────────────┬─────────────────────────────────┘
                         │ 文件系统
┌────────────────────────▼─────────────────────────────────┐
│  outputs/  产物唯一真相源    profiles/ 画像                │
│  var/      SQLite + 会话落盘 + 日志                        │
└──────────────────────────────────────────────────────────┘
```

### 1.1 关键设计决策

**① 门禁做成 in-process MCP tool，不是提示词约定**

把 `atelier_gate_run`、`atelier_artifact_write` 注册成 `@tool`，agent 在产出落盘前**必须**调用。这让「硬门禁阻断」成为代码路径上的事实，而不是靠模型自觉。命中 BLOCK 级时 tool 直接返回错误并附改法，模型无法绕过。

**② Harness 抽象（PRD 14.1 ⚠️ 项）**

```python
class Harness(Protocol):
    async def stream(self, req: TurnRequest) -> AsyncIterator[TurnEvent]: ...
    async def interrupt(self, turn_id: str) -> None: ...
    async def health(self) -> HealthReport: ...
```

`ClaudeSDKHarness` 是唯一实现。**业务层只认 `TurnEvent`**，不出现任何 `claude_agent_sdk` 的类型，避免深度绑定。

**③ 路径收口（PRD 原则一的对策）**

全项目**唯一**允许拼路径的地方是 `server/paths.py`。禁止在业务代码里出现 `os.path.join(ROOT, "outputs", ...)` 或 f-string 拼路径（静态检查会拦）。

**④ 元数据与产物分离**

| 内容 | 位置 | 理由 |
|---|---|---|
| 图片/视频/音频/文档产物 | `outputs/<项目>/` 文件系统 | 可审计、可迁移，PRD 原则一 |
| 会话、消息、选题、日历、发布记录、平台登录态索引 | `var/atelier.db`（SQLite） | 需要查询和关系，不适合文件 |
| 每轮对话原始记录 | `var/sessions/<session_id>/<turn_id>.jsonl` | PRD 13「每轮对话落盘」 |
| 画像 | `profiles/<profile_id>.md` | 人可读、可手改、便于导出 |

---

## 2. 目录结构（子 agent 的文件归属边界）

```
Atelier/
├── pyproject.toml                 # Python 依赖与工具配置
├── package.json                   # 前端（根级脚本代理）
├── atelier/
│   ├── server/
│   │   ├── main.py                # app factory / CORS / 静态挂载 / 路由注册
│   │   ├── config.py              # 配置（根目录、通道、开关）
│   │   ├── paths.py               # ★ 路径唯一收口
│   │   ├── errors.py              # 错误码 → 人话映射
│   │   ├── core/
│   │   │   ├── db.py              # SQLite 连接与迁移
│   │   │   └── models.py          # Pydantic 模型（全局共享契约）
│   │   ├── harness/
│   │   │   ├── base.py            # Harness 协议 + TurnEvent 定义
│   │   │   ├── claude_sdk.py      # ClaudeSDKHarness 实现
│   │   │   ├── tools.py           # in-process MCP tools（门禁/落盘/库查询）
│   │   │   └── registry.py        # provider 注册表
│   │   ├── gates/
│   │   │   ├── base.py            # Gate 协议 / GateResult / 分级
│   │   │   ├── registry.py
│   │   │   ├── wordcount.py       # 各平台字数
│   │   │   ├── compliance.py      # 极限词 / 医疗功效
│   │   │   ├── secret_scan.py     # 出站密钥扫描（BLOCK fail-closed）
│   │   │   └── ai_flavor.py       # AI 味五维（WARN）
│   │   ├── skills/
│   │   │   ├── loader.py          # 扫描 skills/*/SKILL.md + manifest
│   │   │   ├── runner.py          # 就地运行
│   │   │   └── executor.py        # 脚本沙箱执行
│   │   ├── profile/               # 画像域实现
│   │   ├── sessions/              # 会话 / SSE / 断线恢复
│   │   ├── library/               # 内容库实现
│   │   ├── publish/               # 发布域实现
│   │   │   ├── platforms/{base,xiaohongshu,douyin,wechat_mp}.py
│   │   │   ├── precheck.py
│   │   │   └── adapt.py           # 母版 → 平台版本
│   │   └── api/                   # 路由（每域一个文件）
│   ├── skills/                    # 技能资产（每个一个目录 + SKILL.md）
│   └── cli/                       # CLI 入口（chat/skill/doctor/ping/web）
├── web/                           # React 前端
│   └── src/
│       ├── main.tsx  App.tsx
│       ├── styles/tokens.css      # ★ 设计令牌（来自 UI-SPEC）
│       ├── components/            # 基础组件（设计系统）
│       ├── lib/                   # api client / sse client / store
│       └── features/<domain>/     # 每域一个目录
├── outputs/  profiles/  var/      # 运行期数据（.gitignore）
└── docs/  specs/  plans/  design/
```

---

## 3. 分批路线图（回答「第一批做完后面怎么排」）

分批原则：**每批结束都能独立跑出一条用户能用的链路**，不留下「半截功能」。

### M0 · 地基（本批前置，1 轮）

| 交付 | 内容 |
|---|---|
| 仓库骨架 | pyproject / venv / 前端 Vite 骨架 / gitignore / Makefile |
| 路径收口 | `paths.py` + 静态检查规则 |
| Harness 抽象 | 协议 + ClaudeSDKHarness + in-process MCP tools |
| 门禁框架 | Gate 协议 + registry + 4 个内置门禁 + 分级语义 |
| 数据层 | SQLite schema（会话/消息/产物索引/发布记录/平台凭证索引） |
| 前端外壳 | 设计令牌、基础组件、13 页路由骨架、API client |
| 诊断 | `doctor` 17 项检查 + CLI 骨架（`web/chat/skill/doctor/ping`） |

**M0 出口标准**：空项目能启动、doctor 全绿、对话能拿到一句流式回复。

### M1 · 纵向闭环（本批主体）

按 PRD 核心闭环串起来，一次打通：

```
画像(F-A1~A6) → 对话(F-B1~B8) → 能力地图/技能库(F-C1~C10)
   → 内容库(F-G1~G8) → 发布中心(F-G9~G18)
```

**M1 出口标准**（可直接对照 PRD 验收）：
1. 建画像 → 3 分钟内 → 切画像后下一轮产出风格可见变化
2. 对话断网重连，AI 已生成内容不丢
3. 停止生成 2s 内生效
4. 点能力只填入不发送
5. 未配置密钥的技能明确告知缺什么，运行禁用
6. 产物落 `outputs/<项目>/成品|素材`，路径可点击直达
7. 一份母版 → 2 个平台版本，字数超限红标并阻断发布
8. 发布有二次确认，失败给明确原因

### M2 · 策划与发现增强

`F-D5~D13`（博主订阅、RSS 聚合、深度加载、热点日报、事件日历、竞品分析、内容缺口、算法追踪、UGC）
`F-E6~E17`（平台活动日历、日历建议、选题评分、内容矩阵、标题 Hook、内容策略、账号诊断、受众画像、营销策划、直播策划、商单）

- 前置：M1 的选题库与日历已稳定
- 收益：把「今天发什么」从手动变成有数据支撑

### M3 · 制作能力扩展

`F-F7~F15`（金句卡、海报、图表、信息图、对比图、思维导图、表情包、电商图、公众号排版）
`F-F18~F29`（图像增强、尺寸压缩、水印拼接、TTS 多角色、音乐、音频降噪混音）
`F-F34~F50`（字幕翻译、长视频切片、横竖版、相册视频、卡点、片头片尾、章节、论文解读、小说、长文大纲、框架法、数据报告、文档转换）

- 前置：M1 的门禁框架（视觉质检直接挂到 `ai_flavor` 同级门禁）
- 风险最高的一批，建议拆成 3–4 个小批次：视觉 → 音频 → 视频 → 长内容

### M4 · 平台扩展

`F-G22~G28` 补齐快手 / 知乎 / B站 / 视频号；`F-G19~G21`（平台优化建议、定时发布、短链）

- 前置：M1 的平台抽象已被 3 个平台验证过
- 关键：新增平台**只允许**新增 `platforms/*.py` 一个文件，不许改 `base.py`

### M5 · 归因与增长闭环

`F-G32~G36`（评论洞察、ROI、爆款预测、策略建议）
`F-H1~H3`（工作台概览、数据看板、快捷入口）、`F-I5`（本地 Agent 启用）、`F-J6`（gateway 管理）

- 前置：M1 发布记录 + 产物索引已有真实数据
- 出口：「复盘 → 沉淀 → 下次产出更准」的闭环真正合上

### 批次间的硬规则

| 规则 | 说明 |
|---|---|
| **不跳批** | M(n) 未通过出口标准不启动 M(n+1) |
| **不改地基** | 批次内禁止修改 `paths.py` / `harness/base.py` / `gates/base.py` 的公开签名；要改先改 spec |
| **新能力走注册表** | 新门禁 → `gates/registry.py` 注册；新技能 → 加 `skills/<id>/SKILL.md`；新平台 → 加 `platforms/<name>.py`。**不得修改既有文件来加能力** |
| **每个批次独立可发布** | 每批结束 `atelier web` 能启动、能完成该批的出口场景 |

---

## 4. 本批（M0+M1）范围锁定

### 4.1 纳入

| 域 | 功能点 |
|---|---|
| A 画像 | F-A1 六维体系、F-A2 创建向导、F-A4 可视化编辑、F-A5 多画像并行、F-A6 长期记忆 |
| B 对话 | F-B1 流式、F-B2 素材上传、F-B3 结构化附件、F-B4 打字机、F-B5 随时停止、F-B6 断线恢复、F-B7 问答题卡片、F-B8 会话管理 |
| C 能力 | F-C1 两级组织、F-C2 触发语、F-C3 成熟度、F-C4 点击填入、F-C6 五层分区、F-C7 详情抽屉、F-C8 就地运行、F-C9 API 配置表单、F-C10 配置状态标记 |
| G 内容库 | F-G1~F-G8 全部 |
| G 发布 | F-G9~F-G18 全部（首发 3 平台） |
| F 门禁 | F-F1 通用社媒文案、F-F2 去 AI 感改写、F-F4 字数裁剪（作为门禁的验证载体） |
| H/I/J | F-I1 模型配置、F-I2 自检、F-I3 体检、F-I4 密钥管理；F-J1~F-J5 CLI |

### 4.2 明确不纳入（记入 M2/M3/M4/M5）

- 发布**真实调用**平台接口（M1 只做适配 + 预检 + 发布编排，真实发布走 `PublishAdapter` 抽象，首发实现为 **dry-run + 明确的 TODO 标记**，因为需要真实登录态与风控验证）
- 数据回收 / 归因（M5）
- 热点抓取（M2）
- 视频 / 音频生成（M3）
- 账号登录中心（**降级到 M1 的最小可用**：凭证配置 + 登录态标记 + 真校验接口骨架，扫码 UI 放 M4）

> **诚实说明**：真实发布与扫码登录依赖平台风控与真实账号验证，无法在无账号环境端到端验证。M1 会把它们做成**接口完整、行为可替换、默认 dry-run** 的形态，并把验证步骤写进 `docs/RUNBOOK-PUBLISH.md`。这部分是本批的已知缺口，不掩饰。

---

## 5. 验收方式

| 层级 | 方式 |
|---|---|
| 后端 | `pytest`，每个域至少 6 个用例：正常流、边界、错误码、并发、门禁阻断、路径安全 |
| 前端 | 每个 feature 至少 3 个组件测试（渲染 / 交互 / 空态错误态） |
| 端到端 | 一条冒烟脚本：`建画像 → 发一轮对话 → 点能力填入 → 跑一个技能 → 看门禁 → 查内容库 → 生成发布草稿 → 预检` |
| 人工 | 按 §3 的 M1 出口标准 8 条逐条勾 |

---

## 6. 相关文档

- `specs/SPEC-01-foundation.md` — 地基与全局契约（**所有子 agent 必读**）
- `specs/SPEC-02~07` — 各域 spec
- `plans/PLAN-M0-M1.md` — 任务拆解与并行波次
- `design/UI-SPEC.md` — 视觉与交互规范（前端必读）
- `prd/PRD-Atelier-v1.0.md` — 需求来源
