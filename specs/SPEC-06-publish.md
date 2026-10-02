# SPEC-06 · 发布中心域

> 依赖：`SPEC-00`、`SPEC-01`、`SPEC-02`（人设一致性）、`SPEC-05`（媒体挂载）。

## 0. ⚠️ 本批的已知缺口（先说清，不掩饰）

真实发布依赖**真实登录态 + 平台风控**，无法在开发环境端到端验证。本批交付：

| 交付形态 | 说明 |
|---|---|
| ✅ 完整实现 | 母版编辑、多平台适配流式生成、字数门禁、发布前预检、附件挂载、草稿自动保存、二次确认、发布编排与状态机、错误码→人话映射 |
| ⚠️ `PublishAdapter` 抽象 | 三个平台各一个 adapter 文件，签名完整 |
| ⚠️ 默认 **dry-run** | adapter 默认 `dry_run=True`，模拟成功但打日志。真实实现需要账号验证，**放 M4** |
| ✅ `docs/RUNBOOK-PUBLISH.md` | 写真实发布的验证步骤、环境要求、风险提示 |

`platform_creds` 表与登录态字段本批建好但不接扫码（扫码 UI 在 M4）。

---

## 1. 范围

| 功能点 | 本批 | 备注 |
|---|---|---|
| F-G9 母版 + 多平台 | ✅ | |
| F-G10 一键多平台适配 | ✅ | 流式生成，逐字渲染 |
| F-G11 字数校验 | ✅ | 逐平台计数与上限，超限标红 |
| F-G12 发布前预检 | ✅ | 合规硬门禁 + 标题打分 |
| F-G13 人设一致性提醒 | ✅ | **仅提醒不阻断** |
| F-G14 媒体附件 | ✅ | 从内容库挂载 |
| F-G15 真实发布 | ⚠️ 编排完整 + dry-run | 真实调用 M4 |
| F-G16 短信验证码 | ⚠️ 状态机 + UI | 真实等待 M4 |
| F-G17 草稿与排期 | ✅ | 自动保存不丢 |
| F-G18 发布状态跟踪 | ✅ | 逐平台状态卡 |

---

## 2. 平台适配（`publish/adapt.py`）

```python
PLATFORM_LIMITS = {
    "xhs": {"name": "小红书", "forms": ["image", "video"], "title_max": 20,
            "body_max": 1000, "needs_cover": True,  "cover_ratio": "3:4"},
    "dy":  {"name": "抖音",  "forms": ["video"],       "title_max": 55,
            "body_max": 55,    "needs_cover": False, "cover_ratio": None},
    "gzh": {"name": "微信公众号", "forms": ["image", "text"], "title_max": 64,
            "body_max": 20000, "needs_cover": True, "cover_ratio": "2.35:1"},
}
```

**字数计数规则**（`publish/wordcount.py`，中文场景）：
- 中文/日文/韩文字符：1 字 = 1
- 英文单词：1 词 = 1
- emoji：1 个 = 2（平台普遍这样算）
- 空格、标点：不计
- **实现 `count_platform_chars(text, platform) -> int`**，前端只显示结果，**不在前端重复实现**

**适配生成**：对每个选中的平台，起一个 `harness.stream()`，`system_prompt` 里给平台约束表 + 母版原文 + 画像，流式写回 `PlatformVariant.body`，前端逐字渲染（F-G10）。适配**互不影响**：一个平台失败不影响其他平台。

---

## 3. 发布前预检（`publish/precheck.py`）

| 检查 | 分级 | 判定 | 失败时 |
|---|---|---|---|
| 合规风险扫描 | **BLOCK** | 极限词 / 医疗功效 / 违禁品（复用 `gates/compliance.py`） | 阻断，给出命中的词和位置 |
| 各平台字数 | **BLOCK** | 复用 `gates/wordcount.py` | 标红 + 「一键裁剪」按钮 |
| 封面图 | **BLOCK** | 小红书/公众号必须有封面且比例对 | 阻断，提示去内容库挂载 |
| 登录态 | **BLOCK** | 该平台未登录 → 阻断 | 提示去登录中心 |
| 出站密钥扫描 | **BLOCK** | fail-closed | 阻断 |
| 标题打分 | WARN | 钩子/具体度/搜索词命中 三项 0–10 | 告警 + 给改写建议 |
| 人设一致性 | **WARN** | 对照画像 `style` + `preferences` | **仅提醒，绝不阻断**（F-G13 硬要求） |
| 时机建议 | WARN | 当前时段 / 平台特性 | 告警 |

**`PrecheckItem` 结构**见 SPEC-01 §6。
`run_precheck(draft, profile) -> list[PrecheckItem]`，`blocked = any(BLOCK and not passed)`。

---

## 4. 发布编排（`publish/dispatcher.py`）

```
POST /api/publish/{draft_id}/publish  {confirm: true}
   │
   ├─ run_precheck → 有 BLOCK → 422 GateBlocked（带 items）
   ├─ 二次确认（前端已做，服务端再校验 confirm）
   ├─ 逐平台并发（asyncio.gather + 单平台失败隔离）
   │    ├─ 写 publish_records 记录
   │    ├─ 调 adapter.publish(variant) → PublishResult
   │    └─ 更新 PlatformVariant.status
   └─ 返回 {results: [{platform, status, url, error, error_code}]}
```

**平台状态机**：
```
pending → adapting → ready → publishing → sent
                              ↘ failed
                              ↘ awaiting_sms → publishing → sent / failed(timeout)
```

**错误码 → 人话映射**（PRD 10.6 验收：失败要看到明确原因）：
```python
ERROR_HINTS = {
  "dy_auth_4012": "登录态过期，需重新扫码 + 短信验证码",
  "dy_sms_required": "平台要求短信验证码，请在弹窗中输入（5 分钟内有效）",
  "xhs_risk_control": "触发小红书风控，建议降低频率或人工确认后发布",
  "gzh_no_cover": "公众号图文必须有封面图",
  "timeout": "平台响应超时（>60s），可重试",
}
```

**并发与重试**：单平台失败不阻塞其他；失败可单独重试（`POST /api/publish/records/{id}/retry`）；连续失败 3 次不再自动重试。

---

## 5. 平台 Adapter 抽象

```python
class PublishAdapter(Protocol):
    platform: str
    async def check_auth(self) -> AuthState            # 真校验，不只看标记文件（PRD F-G24）
    async def publish(self, v: PlatformVariant, assets: list[str], dry_run: bool) -> PublishResult
    async def schedule(self, v: PlatformVariant, at: datetime) -> None   # P2

@dataclass
class PublishResult:
    ok: bool
    url: str | None
    error_code: str | None
    error: str | None
    raw: dict
```

实现文件：`platforms/xiaohongshu.py` `platforms/douyin.py` `platforms/wechat_mp.py`
M1 三个文件结构完整、校验逻辑真实（字数/封面/表单类型），**只有最后的 `publish()` 走 dry-run**。

**新增平台规则**（写进 `SPEC-00` §3 硬规则）：只允许新增一个 `platforms/<name>.py`，不改 `base.py`。

---

## 6. API 契约

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/publish/platforms` | 平台元信息 + 登录态 + 约束（前端渲染勾选列表） |
| `GET` | `/api/publish/drafts` | 草稿列表 |
| `POST` | `/api/publish/drafts` | 新建 |
| `GET` | `/api/publish/drafts/{id}` | 详情 |
| `PATCH` | `/api/publish/drafts/{id}` | 局部更新（**自动保存，前端 debounce 800ms**） |
| `DELETE` | `/api/publish/drafts/{id}` | 需 confirm token |
| `POST` | `/api/publish/drafts/{id}/adapt` | `{platforms: []}` → `{stream_url}`，SSE 流式回适配结果 |
| `POST` | `/api/publish/drafts/{id}/precheck` | → `{items, blocked}` |
| `POST` | `/api/publish/drafts/{id}/autofix` | `{platform, field}` → 自动裁剪超限内容 |
| `POST` | `/api/publish/drafts/{id}/publish` | `{confirm: true}` → `{results}` |
| `POST` | `/api/publish/records/{id}/retry` | 单条重试 |
| `GET` | `/api/publish/sms/{record_id}` | 短信墙状态轮询 `{need_sms, expires_in}` |
| `POST` | `/api/publish/sms/{record_id}` | 提交验证码 `{code}` |

---

## 7. 前端要点（`web/src/features/publish/`）

照 `design/prototype-v1.html` 的 `#v-publish`：

```
┌──────────────────────────┬──────────────────────────┐
│ 母版内容                   │ 发布前预检  [1 项待处理]   │
│  标题 [____________]      │  ✓ 合规风险扫描          │
│  正文 [textarea]          │  ✗ 抖音标题超字数（硬门禁）│
│  #话题 chips [+加话题]     │    61/55 [一键裁剪]      │
├──────────────────────────┤  ! 人设一致性（软提醒）    │
│ 平台适配      [已生成 2/3]│  ✓ 标题打分              │
│  ☑ 小红书 618/1000 ▓▓▓░░ │  ✓ 封面图                │
│    （预览文本）            │  ✓ 登录态真校验          │
│  ☑ 抖音 61/55 ▓▓▓▓▓(红)  ├──────────────────────────┤
│    （预览文本）            │ 发布状态 [上次 18:02]     │
│  ☐ 微信公众号  未选择      │  ✓ 工具越用越笨·卡1-3   │
├──────────────────────────┤  ✗ Agent 横转竖 [去登录]  │
│ 媒体附件 [+添加]           │  ○ 本次发布   待发        │
└──────────────────────────┴──────────────────────────┘
[草稿自动保存 14:41]  [排期发布]  [发布到 2 个平台]
```

组件：
- `MasterEditor.tsx` — 标题/正文/话题，**debounce 800ms 自动保存**（显示「草稿自动保存 · HH:MM」）
- `PlatformPicker.tsx` — 平台勾选 + 约束说明 + 登录态 chip
- `PlatformVariantCard.tsx` — 逐平台：标题/正文字数 `618/1000` + 进度条 + **超限标红** + 适配文本预览（渐隐遮罩）+ 适配中打字机
- `PrecheckPanel.tsx` — 逐项：✓ 绿 / ! 琥珀 / ✗ 红，硬门禁项带修复按钮
- `MediaAttachments.tsx` — 从内容库挂载，可移除
- `PublishStatusList.tsx` — 逐平台状态卡，失败显示**原因 + 错误码 + 处理按钮**
- `PublishConfirmDialog.tsx` — 二次确认，列出每平台形态与登录态
- `SmsDialog.tsx` — 短信墙弹窗，倒计时 5 分钟

**关键交互**：
- 勾选平台 → 顶栏按钮文案变「发布到 N 个平台」
- 抖音超字数时点主按钮 → toast 警示「硬门禁未解除」，**不发**
- 适配中逐字渲染（复用打字机组件）
- 状态卡动画：发布中（旋转）→ 已发（✓）/ 失败（✗ + 原因）

---

## 8. 验收标准

| # | 标准 | 验证 |
|---|---|---|
| 1 | 一份母版可编辑并多平台选择 | 勾 2 个平台生成 2 个版本 |
| 2 | 逐平台字数校验，超限标红 | 抖音 61/55 标红 |
| 3 | 超限时发布被阻断 | 点发布 → 422 + 前端 toast |
| 4 | 一键裁剪解除超限 | 点「一键裁剪」→ 48/55，门禁解除 |
| 5 | 预检区分硬门禁与软提醒 | 红色阻断 / 琥珀仅告警 |
| 6 | 人设一致性**不阻断** | 人设不一致时仍可发布，只告警 |
| 7 | 发布有二次确认，列出平台与登录态 | 弹窗内容完整 |
| 8 | 失败给明确原因 + 错误码 | 状态卡显示「登录态过期，需重新扫码（dy_auth_4012）」+ [去登录] |
| 9 | 草稿改动自动保存不丢 | 改标题 → 刷新页面内容还在 |
| 10 | 附件可从内容库挂载 | 选中图片 → 出现在附件区 |
| 11 | 单平台失败不影响其他 | 抖音失败，小红书仍成功 |

---

## 9. 测试清单

```python
# test_publish.py（至少 10 个）
test_char_count_rules_zh_en_emoji
test_per_platform_limits_correct
test_precheck_blocks_on_wordcount
test_precheck_warns_on_persona_mismatch
test_precheck_never_blocks_on_warn_only
test_publish_blocked_when_gate_fails
test_publish_requires_confirm
test_single_platform_failure_isolated
test_error_code_mapped_to_human_text
test_draft_autosave_roundtrip
test_douyin_video_only_rejects_image
test_gzh_requires_cover
```
