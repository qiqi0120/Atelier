# Atelier

> 面向社交媒体创作者的**私有内容工作台**。把热点发现、选题策划、内容制作、多平台发布、数据复盘串成一条闭环 —— 让你带着自己的账号上下文工作，而不是每次从零开始。

**个人自用 · 单用户本地运行 · 文件系统是内容的唯一真相源**

---

## 为什么

传统 AI 工具的问题不是「不会写文案」，而是**不知道你是谁**。同一个模型给不同的人写出来的东西没有区别，因为每次对话都是失忆的。

Atelier 的解法是**账号画像驱动**：先建一个六维画像（定位 / 风格 / 受众 / 平台 / 偏好红线 / 长期记忆），此后所有 AI 产出都基于这个上下文；产物落文件系统归档，上下文、过程、成品始终绑在同一个项目里。

## 核心机制：门禁不可绕过

AI 产出必须过确定性门禁。关键在于**门禁不是提示词约定，而是代码路径上的事实**：

- 门禁注册成 Claude Agent SDK 的 **in-process MCP tool**（`atelier_gate_run`）
- agent 想落盘内容，**必须**先调它；命中 BLOCK 级直接返回错误并附改法
- 模型绕不过去 —— 不是「要求它守规矩」，是「不给它绕的路」

分级语义：**硬门禁阻断**（超字数、含密钥、合规风险）· **软提醒不阻断**（AI 味重、人设不符、标题偏弱）。

## 技术栈

| 层 | 选型 |
|---|---|
| AI 运行时 | **Claude Agent SDK**（Python `claude-agent-sdk`），前置 `Harness` 抽象接口，可换 provider |
| 后端 | Python 3.12 + FastAPI · SQLite（元数据）· 文件系统（产物） |
| 前端 | React 18 + TypeScript + Vite · **零 UI 框架**（原生 CSS 变量驱动设计令牌） |
| 媒体 | FFmpeg · Pillow · faster-whisper（本地优先，省成本和隐私） |

## 快速开始

```bash
# 1. Python 环境
uv venv --python 3.12
uv pip install -e ".[dev]"

# 2. 前端
cd web && pnpm install && pnpm build && cd ..

# 3. 起服务（无 API key 也能跑通全链路，走 MockHarness）
ATELIER_MOCK=1 .venv/bin/python -m atelier.cli.main web
# → http://127.0.0.1:8000

# 配了 ANTHROPIC_API_KEY 就走真实模型
.venv/bin/python -m atelier.cli.main web
```

### 验证

```bash
.venv/bin/python -m pytest -q        # 671 passed
cd web && pnpm test                  # 92 passed
.venv/bin/python -m atelier.cli.main doctor   # 环境体检 17 项
.venv/bin/python scripts/smoke_m1.py          # 端到端冒烟 26 条断言
```

## CLI

| 命令 | 作用 |
|---|---|
| `atelier web` | 启动工作台 |
| `atelier chat` | 终端对话 |
| `atelier skill <name>` | 直接跑技能 |
| `atelier doctor` | 环境诊断（15+ 项） |
| `atelier ping` | 连通性检查 |

## 目录

```
atelier/
  server/
    paths.py      ★ 路径唯一收口（全项目唯一允许拼路径的地方）
    harness/      Harness 抽象 + Claude SDK 实现 + 门禁 MCP tools
    gates/        硬门禁/软提醒插件注册表
    skills/       SKILL.md 加载器 + 就地运行器
    profile/ sessions/ library/ publish/   各功能域
  skills/         技能资产（每个一个目录 + SKILL.md）
web/              React 前端（设计令牌 + 17 个基础组件 + 13 路由）
outputs/          产物（唯一真相源，不入库）
profiles/         画像 md（可手改，不入库）
var/              SQLite + 会话落盘（不入库）
```

## 开发方式

**先 spec，再 plan，再并行实现。** 见 `plans/PLAN-M0-M1.md`：

```
specs/SPEC-00 ~ SPEC-07   架构基线 + 六个功能域契约（冻结共享接口）
plans/PLAN-M0-M1.md       任务拆解 + 依赖图 + 文件归属表 + 并行波次
```

并行开发的关键是**文件归属表**：每个子 agent 只写自己那一列，跨域集成统一在收口阶段做。跨域不一致（比如两套字数口径）单看各域都「通过」，只有集成时才暴露。

## 分批路线

| 批次 | 内容 | 状态 |
|---|---|---|
| M0 | 地基：路径收口 / harness 抽象 / 门禁框架 / SQLite / doctor | ✅ |
| M1 | 纵向闭环：画像 → 对话 → 能力地图/技能库 → 内容库 → 发布中心 | ✅ |
| M2 | 策划与发现：博主订阅、RSS、事件日历、竞品分析、选题评分 | 计划中 |
| M3 | 制作能力扩展：视觉 → 音频 → 视频 → 长内容 | 计划中 |
| M4 | 平台扩展：快手/知乎/B站/视频号 + 扫码登录 + 真实发布 | 计划中 |
| M5 | 归因增长闭环：评论洞察、ROI、爆款预测、工作台数据看板 | 计划中 |

每批结束都能独立跑出一条用户能用的链路，不留半截功能。详见 `specs/SPEC-00-overview.md` §3。

## 文档

| 文档 | 内容 |
|---|---|
| `prd/PRD-Atelier-v1.0.md` | 产品需求文档（161 功能点） |
| `design/prototype-v1.html` | **可交互 UI 原型**（13 页，双击浏览器打开） |
| `design/UI-SPEC.md` | 设计规范：令牌 + 25 条交互规则 |
| `specs/SPEC-00~07` | 架构基线与各域契约 |
| `docs/ACCEPTANCE-M1.md` | M1 验收报告 |

## 边界

**不做**：团队协作 / 多租户 SaaS · 移动端 App · 自建大模型训练 · 内容审核仲裁 · 电商直播交易闭环 · 商业化计费

真实发布与扫码登录目前是 **dry-run**（校验逻辑全真，发送为模拟）—— 需要真实账号与平台风控验证，归 M4 批次。详见 `docs/ACCEPTANCE-M1.md` §6。

## 许可

本期不做开源协议决策（个人自用项目）。若未来商业化，需回头做协议合规审查。
