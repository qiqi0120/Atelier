# SPEC-01 · 地基与全局契约

> **所有子 agent 必读。** 本文件定义的东西是共享接口，签名不得擅自更改；要改先改本文件。
> 依赖：`specs/SPEC-00-overview.md`

---

## 1. `server/paths.py` — 路径唯一收口

**铁律：全项目只有这个文件可以拼路径。** 其他任何文件出现 `os.path.join` + 目录名、或 f-string 拼路径，视为违规。

```python
from pathlib import Path

ROOT: Path          # 仓库根，运行时确定（默认 cwd 的上一级，可用 ATELIER_ROOT 覆盖）
OUTPUTS: Path       # ROOT/outputs      产物唯一真相源
PROFILES: Path      # ROOT/profiles     画像 md
VAR: Path           # ROOT/var          SQLite / 会话 / 日志
SKILLS: Path        # ROOT/atelier/skills
VAR_DB: Path        # VAR/atelier.db
SESSIONS: Path      # VAR/sessions

# 项目目录（成品 / 素材 分区，PRD F-G4）
def project_dir(project: str) -> Path
def product_dir(project: str) -> Path      # outputs/<project>/成品
def material_dir(project: str) -> Path     # outputs/<project>/素材
def new_project(name: str) -> Path         # 创建 成品/ 素材/ .session/ 并建索引

# 路径校验（所有外部传入路径必须过这里）
def resolve_inside(base: Path, rel: str) -> Path
    """把外部传入的相对路径解析为 base 内的绝对路径。
    解析结果逃出 base（含 symlink 逃逸）时抛 PathEscapeError。"""

def is_system_path(p: Path) -> bool
    """判断是否系统文件：.session/、.index.json、.atelier* → 禁止删除（PRD F-G7）"""

def rel_to_root(p: Path) -> str             # 统一转成 outputs/... 形式供 UI 显示
def ensure_dirs() -> None                   # 幂等创建所有根目录
```

**项目名校验**：`^[a-z0-9][a-z0-9-_]{0,63}$`，不合法抛 `ValidationError`。禁止 `..`、绝对路径、路径分隔符。

---

## 2. `server/errors.py` — 错误码 → 人话

PRD 原则四：失败要留痕，不许只显示「失败」。

```python
class AtelierError(Exception):
    code: str          # 机器可读
    http: int
    def to_dict(self) -> dict   # {code, message, detail, hint}
```

| code | http | message 示例 | 说明 |
|---|---|---|---|
| `PathEscapeError` | 400 | 路径超出允许范围 | 安全 |
| `ValidationError` | 422 | 项目名不合法：只允许小写字母、数字、-、_ | |
| `NotFound` | 404 | 找不到项目 tool-dumb | |
| `ProfileNotFound` | 404 | 画像不存在或已删除 | |
| `SessionBusy` | 409 | 该会话正在被另一个窗口生成 | PRD F-B12 |
| `HarnessError` | 502 | AI 运行时连接失败 | |
| `HarnessAuthError` | 502 | ANTHROPIC_API_KEY 未配置或无效 | 指向设置页 |
| `HarnessTimeout` | 504 | AI 生成超时（> 120s） | PRD 13 |
| `GateBlocked` | 422 | 硬门禁未通过：抖音标题 61/55 字 | **必须带 detail.gate_items** |
| `SkillMissingKey` | 409 | 缺少密钥 MINIMAX_API_KEY，无法运行「一键成片」 | PRD F-C10 |
| `SkillNotFound` | 404 | |
| `SkillRunFailed` | 500 | 技能执行失败：FFmpeg 返回码 1（见 stderr） | |
| `PlatformAuthExpired` | 409 | 抖音登录态已过期，需重新扫码 | PRD F-G16 |
| `PlatformSmsWall` | 202 | 抖音要求短信验证码，等待 300s | 需 5 分钟有效验证码 |
| `PublishFailed` | 502 | 发布失败：dy_auth_4012 → 登录态过期 | |
| `SystemFileProtected` | 403 | .session/ 为系统文件，禁止删除 | |
| `SnapshotStale` | 200 | 回收失败，保留上次快照 | 非错误，body 带 `stale: true` |

**统一响应体**：
```json
{ "error": { "code": "GateBlocked", "message": "硬门禁未通过", "detail": {...}, "hint": "点『一键裁剪』自动修正" } }
```

---

## 3. `harness/base.py` — Harness 抽象

**业务层只认这里的类型，出现 `claude_agent_sdk` 导入即为违规。**

```python
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Protocol
from enum import Enum

class EventType(str, Enum):
    THINKING_START = "thinking_start"
    THINKING_DELTA = "thinking_delta"     # 独立思考流（PRD F-B1）
    TEXT_DELTA     = "text_delta"         # 正文流
    TOOL_CALL      = "tool_call"          # 工具调用（含门禁调用，前端要显示）
    TOOL_RESULT    = "tool_result"
    QUESTION       = "question"           # 反问 → 前端渲染选项卡片（F-B7）
    ARTIFACT       = "artifact"           # 产物落盘完成
    GATE_RESULT    = "gate_result"        # 门禁结果块
    DONE           = "done"
    ERROR          = "error"

@dataclass
class TurnEvent:
    type: EventType
    turn_id: str
    data: dict = field(default_factory=dict)

@dataclass
class TurnRequest:
    session_id: str
    turn_id: str
    prompt: str
    profile: "Profile | None"           # 已内联好的画像（调用方负责拼）
    attachments: list["Attachment"] = field(default_factory=list)
    system_suffix: str | None = None    # 每轮重申「先查技能库」，对抗指令衰减（PRD 4.2）
    project: str | None = None

class Harness(Protocol):
    name: str
    async def stream(self, req: TurnRequest) -> AsyncIterator[TurnEvent]: ...
    async def interrupt(self, turn_id: str) -> None:
        """必须在 2s 内让生成停止（PRD F-B5 验收标准）。"""
    async def resume(self, turn_id: str) -> "list[TurnEvent]":
        """断线恢复：返回该轮已产生的全部事件（PRD F-B6）。"""
    async def health(self) -> "HealthReport": ...
    async def aclose(self) -> None: ...
```

**实现约束**：
- 单个 `session_id` 同时只允许一个活跃 turn，冲突抛 `SessionBusy`（PRD F-B12）
- `interrupt` 实现顺序：先 `asyncio.Task.cancel()`，再调 SDK 的中断方法兜底
- 每轮事件同时写 `var/sessions/<sid>/<turn_id>.jsonl`，`resume` 从这里读

---

## 4. `harness/claude_sdk.py` — Claude Agent SDK 实现

### 4.0 已验证的 SDK 事实（v0.2.163，2026-10-02 在本机 venv 反射确认）

**导入**
```python
from claude_agent_sdk import (
    query, ClaudeSDKClient, ClaudeAgentOptions, tool, create_sdk_mcp_server,
    AssistantMessage, TextBlock, ThinkingBlock, ResultMessage, SystemMessage,
    UserMessage, ToolUseBlock, ToolResultBlock, StreamEvent,   # StreamEvent 顶层可导
    AgentDefinition, HookMatcher, PermissionMode,
)
```

**真实签名**
```python
query(*, prompt: str | AsyncIterable[dict], options: ClaudeAgentOptions | None = None,
      transport=None)
    -> AsyncIterator[UserMessage|AssistantMessage|SystemMessage|ResultMessage
                    |StreamEvent|RateLimitEvent|ConversationResetMessage]

tool(name: str, description: str, input_schema: type|dict, annotations=None) -> Callable[[fn], SdkMcpTool]
create_sdk_mcp_server(name: str, version='1.0.0', tools: list[SdkMcpTool]|None=None) -> McpSdkServerConfig
ClaudeSDKClient(options: ClaudeAgentOptions | None = None, transport=None)
```

**`ClaudeAgentOptions` 关键字段**（只列与本项目相关的）
```
system_prompt / max_turns / max_budget_usd
allowed_tools / tools / disallowed_tools / permission_mode
cwd / cli_path / env / add_dirs / settings
mcp_servers / strict_mcp_config
model / fallback_model
include_partial_messages        # token 级正文流
include_hook_events / forward_subagent_text
agents: dict[str, AgentDefinition]      # 子 agent
hooks: dict[Literal['PreToolUse','PostToolUse',...], list[HookMatcher]]
skills: list[str] | 'all' | None        # ★ 原生 skills 挂载
output_format: dict | None              # ★ 结构化输出
thinking: ThinkingConfig* / max_thinking_tokens   # ★ 原生思考流
effort: 'low'|'medium'|'high'|'xhigh'|'max'
sandbox: SandboxSettings | None
session_id / resume / continue_conversation / fork_session / session_store
load_timeout_ms / task_budget / max_buffer_size
```

### 4.1 三个关键设计结论

**① 思考流走 SDK 原生，不自己模拟**
`ThinkingBlock` + `thinking: ThinkingConfigAdaptive` + `max_thinking_tokens` → 直接映射为
`THINKING_START` / `THINKING_DELTA`（PRD F-B1「思考过程独立流」）。
`include_partial_messages` **只用于正文 token 级增量**：
`StreamEvent` → `msg.event["type"] == "content_block_delta"` 且 `event["delta"]["type"] == "text_delta"` → `event["delta"]["text"]`。

**② 结构化数据走 `output_format`，不解析 Markdown**
问答题（`question` 事件）、门禁结果、产物清单这类需要稳定 schema 的数据，
用 `ClaudeAgentOptions(output_format=...)` 让 SDK 直接返回结构化结果。理由：解析模型输出的 Markdown 不可靠。

**③ 技能挂载留扩展点，不在 harness 层实现**
SDK 有原生 `skills` 字段，但技能加载逻辑属于技能域（`atelier/skills/` + `atelier/server/skills/`）。
`harness` 层**不 import** 技能模块，改为在 `TurnRequest` 之外提供一个 `extra_options: dict` 扩展点，
由上层传入 skills 配置。保持文件归属清晰，避免并行开发冲突。

**④ 必须提供 MockHarness**
环境变量 `ATELIER_MOCK=1` 时启用写死的流式输出。理由：没有 API key 也要能跑通全部测试与 E2E 冒烟。

### 4.2 必须实现的 5 个进程内工具（`harness/tools.py`）

| 工具名 | 作用 | 关键点 |
|---|---|---|
| `atelier_gate_run` | 对给定内容跑门禁，返回逐项结果 | **BLOCK 级命中时返回 `{"blocked": true, "items":[...], "fix_hint": "..."}`，模型无法绕过** |
| `atelier_artifact_write` | 把产物写入 `outputs/<project>/成品` 或 `/素材` | 内部强制 `paths.resolve_inside`；内部再跑一次 `secret_scan`（双保险） |
| `atelier_library_list` | 查内容库已有产物 | 只读 |
| `atelier_skill_run` | 就地运行某个技能 | 缺密钥抛 `SkillMissingKey`。技能域实现前可暂 `NotImplementedError` |
| `atelier_profile_get` | 读画像某一维 | 供 agent 自查红线 |

**画像注入**：`profile` 由调用方拼成 `system_prompt`（`ClaudeAgentOptions(system_prompt=...)`），格式见 SPEC-02 §4。**不落全局文件**，避免并发画像互相污染（PRD 4.2）。

---

## 5. `gates/base.py` — 门禁框架

```python
class Severity(str, Enum):
    BLOCK = "block"   # 阻断：必须修
    WARN  = "warn"    # 软提醒：只告警（PRD 原则二）

@dataclass
class GateItem:
    gate: str            # 门禁 id
    label: str           # "小红书正文字数"
    severity: Severity
    passed: bool
    actual: int | str | None
    limit: int | str | None
    message: str         # 人话
    fix_hint: str | None # 怎么改

@dataclass
class GateReport:
    items: list[GateItem]
    @property
    def blocked(self) -> bool: return any(i.severity == Severity.BLOCK and not i.passed for i in self.items)
    def to_dict(self) -> dict

class Gate(Protocol):
    id: str
    label: str
    def run(self, content: "GateInput") -> GateItem: ...
```

**注册表**（`gates/registry.py`）：
```python
def register(gate: Gate) -> None       # 装饰器 @register
def run_gates(content: GateInput, gate_ids: list[str] | None = None) -> GateReport
def list_gates() -> list[dict]          # 给前端「门禁说明」用
```

**内置门禁（M1 交付 4 个）**：

| id | 分级 | 检查内容 |
|---|---|---|
| `wordcount` | BLOCK | 各平台字数上限（小红书 1000 / 抖音标题 55 / 公众号 20000） |
| `compliance` | BLOCK | 极限词、医疗功效、违禁品词表；命中即阻断 |
| `secret_scan` | BLOCK | 出站内容里的 API key / token / 私钥，**fail-closed**（扫描器异常时按命中处理） |
| `ai_flavor` | WARN | AI 味五维打分（直接性/节奏/信任度/活人感/精炼度），低于阈值只告警 |

`GateInput`：
```python
@dataclass
class GateInput:
    text: str
    platform: str | None            # 按平台判字数
    title: str | None
    image_paths: list[str]          # 视觉质检用（M3 扩展）
    profile: "Profile | None"       # 人设一致性用
```

---

## 6. `core/models.py` — 共享数据模型

```python
# 画像
class Profile(BaseModel):
    id: str
    name: str
    platforms: list[str]
    identity: str = ""          # 定位
    style: str = ""             # 风格
    audience: str = ""          # 受众
    platform_rules: str = ""    # 平台约束
    preferences: str = ""       # 偏好红线
    memories: list["Memory"] = []
    general_mode: bool = False  # 通用模式：不注入画像
    created_at: datetime
    updated_at: datetime

    def completeness(self) -> dict[str, int]   # 六维各 0-100

class Memory(BaseModel):
    id: str
    text: str
    source: str          # "归因" | "手动" | "对话内记下"
    created_at: datetime
    adopted: bool = True

# 会话
class Session(BaseModel):
    id: str
    title: str
    profile_id: str | None
    created_at: datetime
    updated_at: datetime
    archived: bool = False
    last_turn_id: str | None = None

class Message(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant", "system"]
    text: str
    turn_id: str | None
    attachments: list["Attachment"] = []
    gate_report: dict | None = None
    created_at: datetime

class Attachment(BaseModel):
    id: str
    kind: Literal["image", "video", "audio", "doc"]
    path: str          # 相对 outputs/
    name: str
    size: int
    mime: str

# 技能
class SkillMeta(BaseModel):
    id: str
    name: str
    layer: Literal["发现", "策划", "制作", "发布", "归因", "通用"]
    maturity: Literal["v0", "v1", "v2", "v3"]   # 已验证/可用/需配置/接入中
    trigger: str                                   # F-C2 触发语
    cost: str                                       # "本地 · 免费" / "按量计费 · 需密钥"
    required_keys: list[str]
    params: list["SkillParam"]
    body_markdown: str
    script: str | None

class SkillParam(BaseModel):
    key: str
    label: str
    default: str = ""

# 能力地图
class Capability(BaseModel):
    id: str
    group: str            # "做内容 · 要成品"
    name: str
    trigger: str
    maturity: Literal["v0", "v1", "v2", "v3"]
    skill_id: str | None

# 发布
class PublishDraft(BaseModel):
    id: str
    project: str | None
    title: str
    body: str
    topic_tags: list[str]
    variants: list["PlatformVariant"]
    attachments: list[str]
    created_at: datetime
    updated_at: datetime

class PlatformVariant(BaseModel):
    platform: Literal["xhs", "dy", "gzh"]
    title: str
    body: str
    char_count: int
    char_limit: int
    over_limit: bool
    adapted: bool
    status: Literal["pending", "adapting", "ready", "publishing", "sent", "failed"]
    error: str | None = None
    published_url: str | None = None

class PrecheckItem(BaseModel):
    id: str
    label: str
    severity: Severity
    passed: bool
    message: str
    fix_hint: str | None = None
    platform: str | None = None
```

---

## 7. `core/db.py` — SQLite schema

位置 `var/atelier.db`。**只存元数据，不存产物。**

```sql
CREATE TABLE profiles (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, platforms TEXT NOT NULL,  -- JSON
  identity TEXT, style TEXT, audience TEXT, platform_rules TEXT, preferences TEXT,
  general_mode INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT
);
CREATE TABLE memories (
  id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  text TEXT NOT NULL, source TEXT, adopted INTEGER DEFAULT 1, created_at TEXT
);
CREATE TABLE sessions (
  id TEXT PRIMARY KEY, title TEXT, profile_id TEXT, archived INTEGER DEFAULT 0,
  last_turn_id TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE messages (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL, text TEXT NOT NULL, turn_id TEXT, attachments TEXT,
  gate_report TEXT, created_at TEXT
);
CREATE TABLE artifacts (            -- 产物索引，指向文件系统
  id TEXT PRIMARY KEY, project TEXT NOT NULL, zone TEXT NOT NULL,  -- 成品|素材
  rel_path TEXT NOT NULL, kind TEXT, size INTEGER, mime TEXT,
  session_id TEXT, turn_id TEXT, created_at TEXT
);
CREATE TABLE publish_drafts (
  id TEXT PRIMARY KEY, project TEXT, title TEXT, body TEXT, topic_tags TEXT,
  variants TEXT, attachments TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE publish_records (
  id TEXT PRIMARY KEY, draft_id TEXT, platform TEXT NOT NULL, status TEXT NOT NULL,
  title TEXT, error TEXT, error_code TEXT, published_url TEXT, created_at TEXT
);
CREATE TABLE platform_creds (       -- 凭证密文，绝不存明文
  id TEXT PRIMARY KEY, platform TEXT NOT NULL, account TEXT,
  secret_ref TEXT NOT NULL,        -- 指向 keychain / 加密文件
  state TEXT NOT NULL,             -- unknown|valid|expired
  verified_at TEXT, created_at TEXT
);
CREATE TABLE settings (k TEXT PRIMARY KEY, v TEXT);  -- 密钥掩码、自检结果快照
CREATE TABLE skill_runs (            -- 技能运行记录（M1 收尾补，见下）
  id TEXT PRIMARY KEY,              -- run_id
  skill_id TEXT NOT NULL,
  project TEXT, profile_id TEXT,
  status TEXT NOT NULL,             -- running|done|failed|cost_pending
  params TEXT,                      -- JSON：入参原样留档
  result_markdown TEXT, artifacts TEXT, gate_report TEXT,   -- JSON
  cost_estimate TEXT,               -- JSON
  cost_actual REAL DEFAULT 0.0,
  stdout TEXT, stderr TEXT, returncode INTEGER,
  error TEXT, missing_keys TEXT,    -- JSON
  duration REAL DEFAULT 0.0,
  created_at TEXT, updated_at TEXT
);
```

> **`skill_runs` 是 M1 收尾时补的第 10 张表**（M1 验收报告 §8 的架构性欠账）。
> 之前技能运行记录只存于 `api/capability.py` 的进程内 `_RUNS` 字典，重启即丢。
> 命名用 `skill_runs` 而非 `runs`：M2 之后还会有 RSS 拉取、热点抓取等别的「运行」，
> 通用表名会立刻变味。
> 索引：`idx_skill_runs_skill(skill_id, created_at)`、`idx_skill_runs_project(project, created_at)`。

**约定**：
- 时间统一 ISO8601 UTC 字符串
- JSON 字段用 TEXT 存 JSON
- 外键开启 `PRAGMA foreign_keys=ON`
- 迁移：启动时执行 `schema_version` 检查，缺什么补什么（不引入 Alembic，M1 阶段够用）

---

## 8. API 约定

### 8.0 ★ 路由前缀约定（新增，已踩坑）

`main.py` 的 `_autoload_routers()` 扫描 `atelier/server/api/*.py`，
并执行 `app.include_router(router, prefix=getattr(mod, "ROUTER_PREFIX", "/api"))`。

**因此域模块的 router 一律不要自己带 `/api` 前缀：**

```python
# ✅ 正确
router = APIRouter(tags=["profile"])          # 前缀由 main.py 统一加 /api

# ❌ 错误：会变成 /api/api/profile/... 全部 404
router = APIRouter(prefix="/api", tags=["profile"])
```

如确实需要自定义前缀，才定义模块级 `ROUTER_PREFIX`，此时 router 自身**不带**前缀。

### 8.1 通用约定

| 项 | 约定 |
|---|---|
| 前缀 | `/api` |
| 静态前端 | `/` 挂载 `web/dist`（开发时 Vite proxy 到 8000） |
| 媒体流 | `/api/library/stream?path=...` 必须支持 **HTTP Range**（PRD F-G6），返回 206 |
| 流式 | `POST /api/chat/stream` → `text/event-stream`，事件 `data: {TurnEvent JSON}` |
| 中断 | `POST /api/chat/interrupt` body `{turn_id}` |
| 断线恢复 | `GET /api/chat/turn/{turn_id}` → `list[TurnEvent]` |
| 破坏性 | `DELETE` 类接口必须 `?confirm=<token>`，token 由 `POST /api/<x>/confirm-token` 预生成（前端二次确认用） |
| CORS | 仅 `http://localhost:5173` 与 `http://127.0.0.1:5173`（PRD 13） |
| 跨站写拦截 | 非 `Content-Type: application/json` 或带可疑 `Origin` 的写请求 → 403 |
| 长任务 | 发布/技能运行用 `asyncio.create_task` + 任务表，客户端轮询状态或订阅 SSE；**单任务允许 2 小时**（PRD 13） |
| 超时 | AI 生成 > 120s → 504 `HarnessTimeout`；子进程失败 → 返回 stderr 摘要，不返回 500 空壳 |

---

## 9. 安全基线

| 项 | 要求 |
|---|---|
| 密钥 | 只写不回传；存储走系统 keychain（macOS Keychain / Windows DPAPI / Linux libsecret），降级到 `var/secrets.enc`（AES-GCM，密钥来自 `ATELIER_MASTER_KEY`） |
| 路径 | 所有外部路径经 `paths.resolve_inside`；禁止 `..` 与 symlink 逃逸 |
| 出站扫描 | `secret_scan` 门禁 fail-closed；agent 的 `atelier_artifact_write` 内部再跑一次（双保险） |
| 子进程 | 技能脚本执行用 `shell=False`，参数数组传入，超时强制 kill，stderr 截断 8KB |
| 绑定 | 服务只监听 `127.0.0.1`，默认不开鉴权（本地工具定位），但 CORS 收紧 + 跨站写拦截 |
| 前端 | Markdown 渲染禁 `dangerouslySetInnerHTML`；HTML 预览走 `sandbox` iframe |

---

## 10. 环境与依赖

```toml
# pyproject.toml 核心依赖
requires-python = ">=3.10"
dependencies = [
  "fastapi>=0.115", "uvicorn[standard]>=0.32", "pydantic>=2.9",
  "claude-agent-sdk>=0.1",          # AI 运行时（D1）
  "python-multipart>=0.0.12",       # 素材上传
  "httpx>=0.27",                    # 热榜/平台接口（M2+）
  "markdown-it-py>=3.0",            # 服务端 Markdown（如需）
  "pyyaml>=6.0",
]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "ruff>=0.7", "mypy>=1.13"]
```

前端：`react 18` / `react-dom 18` / `react-router-dom 6` / `typescript 5` / `vite 6` / `lucide-react` / `react-markdown` + `remark-gfm` / `zustand` / `vitest` + `@testing-library/react`

**本机已就绪**：Python 3.12.4（brew）、Node 26.10.0、pnpm 11.19.1、FFmpeg 9.0.2、Chrome 141、uv。

---

## 11. 本文件的不可变条款

以下签名/字段名在 M0+M1 期间**冻结**：
`paths.*` 全部函数名 · `TurnEvent` / `TurnRequest` / `EventType` 枚举值 · `Harness` 协议方法名 · `GateItem` / `GateReport` / `Severity` 字段 · `core/models.py` 全部模型名与字段 · 错误码字符串 · API 路径

发现不够用时：**先提 spec 变更，再改代码**。不要私自加字段——并行开发的子 agent 会因此对不上。
