# SPEC-03 · 对话工作台域

> 依赖：`SPEC-00`、`SPEC-01`。**本域有三条硬验收：断线不丢内容（F-B6）、2s 内停止（F-B5）、问答题不重复（F-B7）。**

## 1. 范围

| 功能点 | 本批 | 备注 |
|---|---|---|
| F-B1 流式对话 | ✅ | SSE，含独立思考流 |
| F-B2 素材上传 | ✅ | 按钮/拖拽/粘贴三通道 |
| F-B3 结构化附件 | ✅ | 消息只显示实际输入文字 |
| F-B4 打字机渲染 | ✅ | 前端增量渲染，≈2–4 字/帧 |
| F-B5 随时停止 | ✅ | **2s 内生效** |
| F-B6 断线恢复 | ✅ | 从服务端取回该轮结果 |
| F-B7 问答题卡片 | ✅ | 已答不重复出现 |
| F-B8 会话管理 | ✅ | 新建/重命名/归档/删除 |
| F-B9 末轮重试 | ⏭ M2 | |
| F-B10 场景推荐 | ✅ | 空态 4 个场景 |
| F-B11 心跳提示 | ✅ | 30s 静默显示「未卡住」 |
| F-B12 多窗口防撞 | ✅ | 检测占用自动开新会话 |

---

## 2. 模块

| 文件 | 归属 | 职责 |
|---|---|---|
| `atelier/server/sessions/store.py` | 本域 | 会话/消息 CRUD + 落盘 |
| `atelier/server/sessions/manager.py` | 本域 | ★ 活跃 turn 管理、并发锁、断线恢复 |
| `atelier/server/sessions/sse.py` | 本域 | SSE 事件序列化 |
| `atelier/server/api/chat.py` | 本域 | 路由 |
| `atelier/server/harness/claude_sdk.py` | 地基域 | 被调用（不改） |
| `web/src/features/chat/` | 本域 | 会话栏 + 消息流 + 输入框 |
| `web/src/lib/sse.ts` | 本域 | SSE 客户端（含断线重连） |

---

## 3. ★ Turn 生命周期

```
POST /api/chat/stream {session_id, text, attachments[], profile_id}
   │
   ├─ 检查 session 是否被其他 turn 占用 → 是则 409 SessionBusy（F-B12）
   ├─ 写入 user message（落盘）
   ├─ 创建 turn_id，写 var/sessions/<sid>/<turn_id>.jsonl
   ├─ 组装 TurnRequest：prompt = BASE + profile_prefix + system_suffix
   │
   └─ 逐个 yield TurnEvent，同时：
        · append 到 jsonl（每条一行，断线恢复的真相源）
        · 写 messages 表
        · 写 artifacts 索引
        │
   SSE event: data: {"type":"text_delta","turn_id":"...","data":{"text":"..."}}
   ...
   SSE event: data: {"type":"done","turn_id":"...","data":{"gate":{...}}}
```

**事件类型**（`EventType`，见 SPEC-01 §3）：`thinking_start` `thinking_delta` `text_delta` `tool_call` `tool_result` `question` `artifact` `gate_result` `done` `error`

### 3.1 问答题卡片（F-B7）

agent 需要反问时发 `question` 事件：
```json
{"type":"question","turn_id":"...","data":{
  "question_id":"q_01",
  "text":"补一个信息，我出终版",
  "options":[{"key":"A","label":"保持这个语气，直接出终版"}, ...],
  "multiple": false
}}
```
**服务端**在 `messages` 表存 `question`，并在会话内维护 `answered_questions: set[str]`。
已答过的问题：后续轮次 agent 再发同 `question_id` 时**丢弃不发**（由服务端过滤，agent 可能重复问）。

用户点选项 → `POST /api/chat/answer {session_id, question_id, option_key}` → 服务端记录并把选项文本作为新的 user message 继续生成。

### 3.2 中断（F-B5）

```
POST /api/chat/interrupt {turn_id}
   → manager 找到活跃 task
   → asyncio.Task.cancel()  （先做这个，通常 < 100ms 生效）
   → harness.interrupt(turn_id) 兜底
   → 发 done 事件，data:{"interrupted": true, "partial": true}
```
**验收硬指标：从点击到界面停止打字 ≤ 2s。** cancel 之后已经 yield 的 `text_delta` 保留（用户不丢已生成内容）。

### 3.3 断线恢复（F-B6）

```
GET /api/chat/turn/{turn_id}  →  {"events": [...], "status": "running|done|interrupted|error"}
```
前端 SSE 客户端：
1. `EventSource` onerror → 指数退避重连（0.5s → 1s → 2s → 4s，上限 5 次）
2. 重连成功后调 `GET /api/chat/turn/{turn_id}` 拉全量事件，用 `turn_id + 事件序号` 去重补齐
3. 若该轮已 `done`，直接进入完成态

**必须做到**：断网 10 秒后恢复，AI 已生成的内容不丢失、不重复渲染。

---

## 4. 素材上传（F-B2/F-B3）

```
POST /api/chat/upload  (multipart)
  → 落到 outputs/_uploads/<session_id>/<uuid>.<ext>
  → 写 artifacts 表（zone=素材）
  → 返回 {id, kind, name, size, mime, path}
```
限制：单文件 ≤ 200MB；类型 `image/* video/* audio/* .pdf .docx .md .txt .csv .xlsx`；其余 400 并说明原因。

**F-B3 关键规则**：附件作为结构化字段传给 agent（`Attachment` 对象，含真实路径供 agent 读取），**不把文件名拼进用户 prompt**。消息气泡只显示用户实际输入的文字，附件单独以 chip 挂在气泡下方（UI-SPEC 规则 8）。

粘贴通道：前端监听 `paste` 事件，`e.clipboardData.items` 里 `type.startsWith('image/')` 的走 `upload_files`。

---

## 5. 会话管理（F-B8）

| API | 说明 |
|---|---|
| `GET /api/chat/sessions` | 按 updated_at 倒序，分组：今天/昨天/更早/已归档 |
| `POST /api/chat/sessions` | 新建，`title` 取首条消息前 20 字 |
| `PATCH /api/chat/sessions/{id}` | 重命名 `{title}` |
| `POST /api/chat/sessions/{id}/archive` | 归档 |
| `DELETE /api/chat/sessions/{id}` | 需 confirm token |
| `GET /api/chat/sessions/{id}/messages` | 分页倒序 |

**F-B12 多窗口防撞**：`POST /api/chat/stream` 时服务端检查 `session.locked_by`（客户端上报的 `client_id`）。
不同 `client_id` 撞上 → 返回 409 `SessionBusy`，前端**自动新建会话并把消息带过去**，同时 toast「该会话正在其他窗口生成，已开新会话」。

---

## 6. 前端要点（`web/src/features/chat/`）

严格照 `design/prototype-v1.html` 的 `#v-chat`：

```
┌────────────┬──────────────────────────────────────────┐
│ ＋新会话    │  消息流（滚动到底）                        │
│ 今天        │   user 气泡（灰底）                       │
│  · 会话1    │   assistant 气泡（白底）                  │
│  · 会话2    │     ├ details 思考过程（折叠 + 耗时）      │
│ 昨天        │     ├ 正文（打字机）                       │
│ 已归档      │     ├ 产物卡（路径 chip + 打开目录/去发布）  │
│            │     ├ 门禁结果块（PASS/WARN 逐项）          │
│ 画像注入中  │     └ 问答题卡片                           │
└────────────┴──────────────────────────────────────────┘
┌──────────────────────────────────────────────────────┐
│ [附件 chips]                                          │
│ textarea                                               │
│ 📎 📁 🎤  ...                    [停止生成] [发送]     │
│ Enter 发送 · Shift+Enter 换行 · 素材可拖入或粘贴          │
└──────────────────────────────────────────────────────┘
```

组件：
- `SessionList.tsx` — 分组、hover 出重命名/归档按钮
- `MessageList.tsx` — 消息渲染；`useReducer` 管理流式状态
- `MessageBubble.tsx` — 按 event 累积渲染四类内容
- `ThinkingBlock.tsx` — `<details>` 折叠，显示耗时
- `GateBlock.tsx` — 门禁结果表，BLOCK 红色 / WARN 琥珀
- `ArtifactCard.tsx` — 产物 + 路径 chip（点击 `data-go` 到内容库）
- `QuestionCard.tsx` — 选项卡片；点击后锁定折叠为「已确认 + 你的选择」
- `Composer.tsx` — 输入框、附件、拖拽高亮、粘贴、Enter/Shift+Enter
- `StreamStopButton.tsx` — 生成中替换发送按钮
- `HeartbeatHint.tsx` — 静默 30s 显示「未卡住，继续生成中」
- `SceneSuggestions.tsx` — 空态 4 个场景卡（追热点/拆爆款/去 AI 感/出视频）

**打字机（F-B4）**：后端已按增量推 `text_delta`，前端**直接逐块 append**，不再做二次逐字动画（避免双重延迟）。每帧追加 ≤ 4 字，超长块分帧（`requestAnimationFrame`）。已回放的历史消息不重播打字机。

---

## 7. 验收标准

| # | 标准 | 验证 |
|---|---|---|
| 1 | 断网后重连，AI 已生成内容不丢失 | DevTools 离线 10s → 恢复，内容完整且无重复 |
| 2 | 停止生成 2s 内生效 | 点击到光标停止，计时 ≤ 2s |
| 3 | 问答题点击后不再重复出现 | 答完继续对话 3 轮，不重复出现 |
| 4 | 素材拖入后消息区不显示文件名污染 | 拖入 PDF + 粘贴图片，消息只显示输入文字 |
| 5 | 思考过程独立可折叠 | 折叠/展开正常，显示耗时 |
| 6 | 每轮结束落盘 | `var/sessions/<sid>/<turn_id>.jsonl` 存在且内容与界面一致 |
| 7 | 产物路径可点击直达内容库 | 点路径 → 跳内容库并定位 |
| 8 | 并发窗口防撞 | 两个标签页开同一会话，第二个自动开新会话 |
| 9 | 门禁结果内嵌在消息里 | 能看到逐项 PASS/WARN |

---

## 8. 测试清单

```python
# test_chat.py（至少 10 个）
test_stream_emits_text_delta_then_done
test_interrupt_stops_within_2s
test_interrupt_keeps_partial_text
test_resume_returns_all_events
test_resume_dedup_by_index
test_question_answered_not_repeated
test_concurrent_session_returns_409
test_new_session_auto_switch_on_409
test_upload_rejects_unsupported_type
test_turn_persisted_to_jsonl
```
