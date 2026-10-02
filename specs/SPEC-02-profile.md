# SPEC-02 · 账号画像域

> 依赖：`SPEC-00`、`SPEC-01`。**PRD 4.2 的「画像作为消息前缀内联，不落全局文件」是本域最关键的约束。**

## 1. 范围

| 功能点 | 本批 | 说明 |
|---|---|---|
| F-A1 六维画像体系 | ✅ | 定位/风格/受众/平台/偏好红线/长期记忆 |
| F-A2 画像创建向导 | ✅ | 4 步：基础信息 → 社媒链接 → 运营意图 → 偏好红线，**可中途跳过** |
| F-A4 可视化编辑 | ✅ | 六维分别编辑保存，Markdown 渲染 |
| F-A5 多画像并行 | ✅ | 多画像共存一键切换，同一画像跨多平台 |
| F-A6 长期记忆沉淀 | ✅ | 归因结论自动沉淀 + 用户主动「记住这个偏好」 |
| F-A3 AI 辅助生成画像 | ⏭ M2 | 需要抓取社媒链接内容 |
| F-A7 平台数据写回 | ⏭ M5 | |
| F-A8 导出/对比 | ⏭ M2 | 本批只做导出 |

---

## 2. 模块

| 文件 | 归属 | 职责 |
|---|---|---|
| `atelier/server/profile/store.py` | 本域 | 画像 CRUD、记忆 CRUD、落盘 `profiles/<id>.md` |
| `atelier/server/profile/prompt.py` | 本域 | ★ 画像 → 消息前缀（注入 harness） |
| `atelier/server/profile/wizard.py` | 本域 | 创建向导的状态机 |
| `atelier/server/api/profile.py` | 本域 | FastAPI 路由 |
| `web/src/features/profile/` | 本域 | 六维编辑页 + 向导 + 记忆面板 |

---

## 3. 存储

**双写**：SQLite（查询/切换快）+ `profiles/<id>.md`（人可读、可手改、可导出）。
以 SQLite 为准；启动时若 md 存在且 `updated_at` 更新，则反向导入（支持用户手改 md）。

`profiles/<id>.md` 格式：
```markdown
---
id: ai-efficiency
name: AI 效率观察
platforms: [xhs, dy, gzh]
general_mode: false
updated_at: 2026-10-02T15:00:00Z
---

## identity
（正文）

## style
## audience
## platform_rules
## preferences

## memories
- [归因] 反常识 + 亲手实测组合，中位播放是均值 3.8 倍
```

---

## 4. ★ 画像注入格式（`prompt.py`）

**这是整个产品的地基，所有 AI 产出都经过它。**

```python
def build_profile_prefix(profile: Profile | None) -> str:
    if profile is None or profile.general_mode:
        return ""   # 通用模式：完全不注入
    return f"""<account_profile>
## 定位
{profile.identity}

## 风格
{profile.style}

## 受众
{profile.audience}

## 平台约束
{profile.platform_rules}

## 偏好红线（禁止违反）
{profile.preferences}

## 长期记忆
{chr(10).join('- ' + m.text for m in profile.memories) or '（暂无）'}
</account_profile>"""
```

**注入方式**：`ClaudeAgentOptions(system_prompt=BASE_SYSTEM + profile_prefix + system_suffix)`。
**不写全局文件、不写数据库字段**——每次请求现拼，因此两个画像并发对话不会互相污染（PRD 4.2 验收）。

**每轮重申（对抗长对话指令衰减，PRD 4.2）**：在每次 `TurnRequest.system_suffix` 末尾追加：

```
【流程提醒】动手前先查技能库（skills/ 目录），有现成技能就用，不要从零手搓。
产出落盘前必须调用 atelier_gate_run 跑门禁；图片等产物用 atelier_artifact_write 写入。
```

---

## 5. API 契约

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/profiles` | 列表（含 completeness），按 updated_at 倒序 |
| `POST` | `/api/profiles` | 新建 `{name, platforms}` → 返回带 `wizard_token` 的空画像 |
| `GET` | `/api/profiles/{id}` | 详情 |
| `PATCH` | `/api/profiles/{id}` | 局部更新任一维，自动重算 completeness |
| `DELETE` | `/api/profiles/{id}` | 需 `?confirm=<token>`；**有会话引用时返回 409** |
| `POST` | `/api/profiles/{id}/wizard/step` | `{step, data}` → `{next_step, progress}`；`step: done` 结束 |
| `DELETE` | `/api/profiles/{id}/wizard` | 中途放弃，保留已填内容 |
| `GET` | `/api/profiles/{id}/memories` | 记忆列表 |
| `POST` | `/api/profiles/{id}/memories` | 手动加记忆 `{text}` |
| `DELETE` | `/api/profiles/{id}/memories/{mid}` | |
| `POST` | `/api/profiles/{id}/general-mode` | `{enabled}` 切通用模式 |
| `GET` | `/api/profiles/{id}/export` | 下载 `.md` |
| `GET` | `/api/profiles/{id}/preview` | 预览渲染后的 `system_prompt`（调试用，**必须能看见真实注入内容**） |

**创建向导 4 步**：

| step | 收集 | 可跳过 |
|---|---|---|
| 1 基础信息 | 账号名、主平台、内容方向 | 否（最少要账号名） |
| 2 社媒链接 | 各平台主页 URL | ✅ |
| 3 运营意图 | 想涨粉/接商单/做转化 | ✅ |
| 4 偏好红线 | 不想出现的话、禁忌话题 | ✅ |

**全程 < 3 分钟**：第 1 步只需账号名即可「完成」，其余用「先跳过」按钮。向导顶部显示进度 `2/4`，跳过也前进。

---

## 6. 前端要点（`web/src/features/profile/`）

**页面结构**（严格按 `design/prototype-v1.html` 的 `#v-profile`）：

```
┌──────────┬──────────────────────────────────────────────┐
│ 六维导航  │ 维度标题 + [AI 帮我补全] [保存]                │
│ 定位 100% │ ┌──────────────┬────────────────────────────┐ │
│ 风格 92%  │ │ Markdown 编辑 │ 实时渲染预览               │ │
│ 受众 78%  │ │ (mono 字体)   │                            │ │
│ 平台 100% │ │ 字数计数      │                            │ │
│ 红线 85%  │ └──────────────┴────────────────────────────┘ │
│ 记忆 66%  │ 偏好红线列表（可删）                          │
│          │ 长期记忆列表（来源 + 时间）                    │
│ 完整度 86%│ 通用模式开关                                   │
└──────────┴──────────────────────────────────────────────┘
```

组件：
- `ProfileEditor.tsx` — 左导航 + 右编辑区；编辑即实时预览（300ms debounce）
- `DimNav.tsx` — 六维项 + 完整度进度条
- `ProfileWizard.tsx` — 模态 4 步向导，**每步都有「先跳过」**
- `MemoryPanel.tsx` — 记忆列表 + 手动添加
- `GeneralModeToggle.tsx` — 开关，切换时 toast 说明影响

**交互规则**（来自 UI-SPEC §5）：
- 保存成功 toast：「已保存 · 下一轮对话立即生效」
- 切画像后回到对话页，下一轮产出风格变化要**肉眼可见**（验收项）
- 侧边栏底部的画像切换器与本页面双向同步

---

## 7. 验收标准

| # | 标准 | 验证方式 |
|---|---|---|
| 1 | 无画像状态下可完成任意创作任务（通用模式） | 关掉画像 → 对话能正常产出 |
| 2 | 画像创建全程 < 3 分钟，可中途跳过 | 手动走一遍 4 步 |
| 3 | 切换画像后下一轮对话产出风格可见变化 | 建两个风格迥异的画像各发一轮，对比 |
| 4 | 两个画像的对话不互相污染 | 并发开两个会话各用不同画像，检查 `preview` 接口注入内容不同 |
| 5 | 画像以消息前缀内联，不落全局文件 | `grep -r "profile" var/` 无画像正文文件；`/preview` 返回值与 `system_prompt` 一致 |
| 6 | 每轮对话末尾重申「先查技能库」 | 检查实际 `TurnRequest.system_suffix` |
| 7 | 长期记忆可手动添加，下一轮生效 | 加一条「不用 emoji」→ 下一轮产出确实没有 emoji |

---

## 8. 测试清单

```python
# test_profile.py（至少 8 个）
test_create_minimal_profile          # 只有名字也能建
test_wizard_skip_all_steps           # 全跳过仍完成，progress 到 4/4
test_profile_prefix_contains_all_dims
test_profile_prefix_empty_in_general_mode
test_two_profiles_no_pollution        # 并发两个请求，前缀不同
test_memory_add_and_inject
test_delete_profile_with_sessions_409
test_computation_scores              # 六维完整度计算
```
