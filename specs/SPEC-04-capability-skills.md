# SPEC-04 · 能力地图与技能库域

> 依赖：`SPEC-00`、`SPEC-01`。**「薄壳 + 厚知识库」的用户可见部分。**

## 1. 范围

| 功能点 | 本批 | 备注 |
|---|---|---|
| F-C1 两级能力组织 | ✅ | 按用户目标分组，不按文件格式 |
| F-C2 触发语说明 | ✅ | 每个能力一句「当你说 XX 时使用」 |
| F-C3 成熟度透明 | ✅ | 已验证/可用/需配置/接入中 |
| F-C4 点击即填入 | ✅ | **不自动发送** |
| F-C5 搜索过滤 | ⏭ M2 | |
| F-C6 五层技能分区 | ✅ | 发现/策划/制作/发布/归因/通用 |
| F-C7 技能详情抽屉 | ✅ | SKILL.md 全文 |
| F-C8 就地运行 | ✅ | 填参数直接跑，Markdown 渲染结果 |
| F-C9 API 配置表单 | ✅ | 卡内配置，掩码回显，留空不覆盖 |
| F-C10 配置状态标记 | ✅ | 缺密钥带 `!`，运行禁用并说明原因 |
| F-C11 技能搜索 | ⏭ M2 | |

---

## 2. 技能资产格式

```
atelier/skills/
├── xhs-card/
│   ├── SKILL.md          # 必需：front-matter + 正文
│   ├── manifest.json     # 可选：参数 schema、产出物声明
│   └── run.py            # 可选：确定性执行体
├── de-ai/SKILL.md
└── ...
```

**SKILL.md front-matter**：
```markdown
---
id: xhs-card
name: 小红书知识卡
layer: 制作              # 发现|策划|制作|发布|归因|通用
maturity: v0             # v0 已验证 | v1 可用 | v2 需配置 | v3 接入中
trigger: 当你说「做成小红书图文」「知识卡」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: title, label: 标题, default: ""}
  - {key: count, label: 张数, default: "3"}
  - {key: size, label: 尺寸, default: "1080×1440"}
outputs: [image]
paid: false
---

# 小红书知识卡
正文即给 agent 看的操作手册……
```

**M1 必须交付 12 个技能**（覆盖 PRD 12.1 的 P0 制作核心）：

| id | 层 | 成熟度 | 需密钥 |
|---|---|---|---|
| `xhs-card` 小红书知识卡 | 制作 | v0 | — |
| `de-ai` 去 AI 感改写 | 制作 | v0 | — |
| `crop` 字数裁剪/摘要 | 制作 | v0 | — |
| `style-transfer` 风格迁移 | 制作 | v0 | — |
| `social-copy` 通用社媒文案 | 制作 | v0 | — |
| `wechat-layout` 公众号排版 | 制作 | v0 | — |
| `viral-decode` 爆款拆解 | 策划 | v0 | — |
| `precheck` 发布前预检 | 发布 | v0 | — |
| `gate-explain` 门禁说明 | 通用 | v0 | — |
| `one-video` 一键成片 | 制作 | **v2** | `MINIMAX_API_KEY` |
| `aigc-image` AI 生图 | 制作 | **v2** | `MINIMAX_API_KEY` |
| `doctor` 环境体检 | 通用 | v0 | — |

> 前 9 个 `maturity: v0` 且**真正可跑**（纯 Python/规则实现，不依赖外部服务）；后 3 个标 `v2`/`v3` 并演示「缺密钥 → 运行禁用」的正确行为。

---

## 3. 能力地图数据

`atelier/server/skills/loader.py` 扫描 `skills/*/SKILL.md`，产出 `SkillMeta[]`。
能力地图（`Capability[]`）**从技能派生**，映射表写在 `capabilities.toml`：

```toml
[groups]
"做内容 · 要成品" = { desc = "给一句主题，产出能直接发的东西" }
"做运营 · 要动作" = { desc = "把「今天发什么」变成明确的下一步" }
"做账号 · 要增长" = { desc = "用真实数据反过来改内容" }
"做系统 · 要配置" = { desc = "工具坏了、缺密钥、想体检时用" }

[[items]]
id = "xhs-card"
group = "做内容 · 要成品"
```

**规则**：
- 分组顺序按 TOML 中 `[groups]` 出现顺序
- `maturity` 从技能继承
- 技能不存在 → 该能力不显示（**能力地图不能有死链**）

---

## 4. 模块

| 文件 | 归属 | 职责 |
|---|---|---|
| `atelier/skills/<id>/` | 技能域 | 12 个技能目录 |
| `atelier/server/skills/loader.py` | 地基域 | 扫描 + 解析 SKILL.md（带缓存，mtime 变更才重扫） |
| `atelier/server/skills/manifest.py` | 技能域 | capabilities.toml 解析 |
| `atelier/server/skills/runner.py` | 技能域 | ★ 就地运行 |
| `atelier/server/skills/executor.py` | 技能域 | 脚本沙箱执行 |
| `atelier/server/api/capability.py` | 技能域 | 能力地图 + 技能库路由 |
| `web/src/features/capability/` | 技能域 | 能力卡 |
| `web/src/features/skills/` | 技能域 | 技能卡 + 抽屉 |

---

## 5. API 契约

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/capabilities` | `{groups: [{name, desc, items: [Capability]}]}` |
| `GET` | `/api/skills` | `?layer=` 过滤，返回 `SkillMeta[]`（不含 `body_markdown`，避免响应过大） |
| `GET` | `/api/skills/{id}` | 含 `body_markdown` 全文 |
| `POST` | `/api/skills/{id}/run` | `{params, project, profile_id}` → `{run_id, stream_url}` |
| `GET` | `/api/skills/runs/{run_id}` | `{status, stdout, result_markdown, artifacts[], error}` |
| `GET` | `/api/keys` | 已配置密钥的**掩码**列表（`sk-****3f7a`），**永不返回明文** |
| `POST` | `/api/keys` | `{platform, key_name, value}` → 只写 |
| `DELETE` | `/api/keys/{key_name}` | 清除 |

**密钥规则（PRD F-C9/F-I4，硬要求）**：
1. 只写不回传：`GET /api/keys` 只给 `sk-****3f7a` 形式的掩码
2. **留空不覆盖**：`POST /api/keys` 传入空值时保持原值不变，返回 `{"unchanged": true}`
3. 存 keychain，降级到 `var/secrets.enc`

---

## 6. 就地运行器（F-C8）

```python
async def run_skill(skill_id, params, project, profile_id) -> RunResult
```

执行流程：
1. **前置检查**：缺 `required_keys` → 抛 `SkillMissingKey`，message 写明缺哪个
2. `paid: true` 的技能 → **先返回费用预估**，需 `POST /api/skills/{id}/run {confirm_cost: true}` 才真跑（PRD 原则三）
3. 拼 `TurnRequest`（注入画像 + 触发语），调 `harness.stream()`
4. agent 调 `atelier_artifact_write` 落盘 → 收集产物路径
5. 跑 `gates.run_gates()` → 附在结果里
6. 返回 `{result_markdown, artifacts, gate_report, cost_actual}`

**脚本型技能**（有 `run.py`）：`executor.py` 用 `asyncio.create_subprocess_exec`（**`shell=False`**），
工作目录 = `outputs/<project>/`，超时默认 600s（长任务允许 2h），失败时返回 **stderr 摘要 8KB + 返回码**，不许只报 500。

---

## 7. 前端要点

### 能力地图（`features/capability/`）

照 `design/prototype-v1.html` 的 `#v-capability`：
- 4 个分组，每组标题 + 一句说明 + 「N 项能力」chip
- 3 列网格的能力卡：图标 + 名称 + **触发语**（F-C2）+ 成熟度 badge（底部对齐）
- hover：边框变主色 + 上浮 2px + 右上角出现「填入输入框 →」
- **点击 → 跳对话页 + 填入 `帮我做「XXX」` + 聚焦输入框 + 主色光晕动画 + toast「已填入输入框，确认后点发送」**
- **绝对不自动发送**（F-C4 硬要求）

### 技能库（`features/skills/`）

- 6 个分区（发现/策划/制作/发布/归因/通用），每区标题 + 「N 个 · M 个已验证」
- 技能卡：图标 + 名称 + 成熟度 + 两行描述（`-webkit-line-clamp:2`）+ 成本 chip + 「详情 / 运行」
- **缺密钥的卡**：置灰 + 右上角橙色 `!` 角标 + hover 提示「缺 MINIMAX_API_KEY，运行已禁用」

**抽屉（详情 + 运行 + 配置，全在一个抽屉里）**：
```
┌─────────────────────────────────────┐
│ 小红书知识卡 [已验证]            [×] │
│ [skill/xhs-card] [制作层] [本地·免费]│
├─────────────────────────────────────┤
│ SKILL.md 渲染正文（Markdown）        │
│ ── 运行参数 ──                      │
│  标题 [__________]                  │
│  张数 [3]  尺寸 [1080×1440]         │
│ ── API 配置 ──                      │
│  MiniMax API Key [••••••••] 👁      │
│  ⚠️ 当前未配置，运行按钮已禁用        │
│ ── 产物落盘位置 ──                   │
│  [outputs/xhs-card/]                │
└─────────────────────────────────────┘
│ 就地运行会写入 outputs/<项目>/  [取消] [运行] │
```

- 缺密钥时**运行按钮变成「缺密钥，已禁用」且 disabled**，tooltip 说明缺哪个
- `paid: true` 的技能：点运行先弹费用确认（PRD 原则三）
- 配置了密钥后回显掩码 `••••3f7a`，不显示明文

---

## 8. 验收标准

| # | 标准 | 验证 |
|---|---|---|
| 1 | 用户能通过能力地图找到任何功能，不需要知道技术名称 | 找「把视频转成竖版」→ 能力地图搜到 |
| 2 | 未配置密钥的技能不会让用户困惑 | 一键成片卡显示 `!` + 说明缺什么 + 运行禁用 |
| 3 | 能力成熟度对用户可见 | 4 种 badge 都能看到 |
| 4 | 点能力只填入不自动发送 | 点后看输入框有内容、消息区没新增 |
| 5 | 12 个技能全部有 SKILL.md 且可加载 | `/api/skills` 返回 12 条 |
| 6 | v0 技能真能跑出产物 | 跑 `xhs-card` → outputs 下出现文件 |
| 7 | 密钥只写不回传 | `GET /api/keys` 只见掩码；留空保存返回 unchanged |
| 8 | 付费技能先给费用预估 | 跑 `one-video` 弹费用确认 |

---

## 9. 测试清单

```python
# test_skills.py（至少 8 个）
test_loader_parses_all_12_skills
test_capabilities_have_no_dead_links        # 每条 capability 都能找到 skill
test_missing_key_disables_run               # 409 SkillMissingKey
test_key_write_never_returns_plaintext
test_key_empty_value_does_not_overwrite
test_paid_skill_requires_cost_confirm
test_script_failure_returns_stderr_summary
test_run_writes_artifacts_to_outputs
```
