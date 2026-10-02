# SPEC-05 · 内容库域

> 依赖：`SPEC-00`、`SPEC-01`。文件系统是唯一真相源，**路径解析全部走 `paths.py`**。

## 1. 范围

| 功能点 | 本批 | 备注 |
|---|---|---|
| F-G1 项目化归档 | ✅ | 产物按项目目录组织 |
| F-G2 目录树浏览 | ✅ | 面包屑逐级下钻 |
| F-G3 类型过滤 | ✅ | 全部/图片/视频/音频/文档 |
| F-G4 成品/素材分区 | ✅ | 项目内分区 |
| F-G5 多格式预览 | ✅ | 图片/视频/音频/HTML(sandbox)/Markdown |
| F-G6 媒体流式回放 | ✅ | **Range 请求**，不一次性加载 |
| F-G7 删除保护 | ✅ | 二次确认 + 显式声明「及其全部内容」；系统文件禁止删 |
| F-G8 产物路径转链接 | ✅ | 对话中的路径可点击直达 |

---

## 2. 目录约定

```
outputs/
├── _uploads/                    # 上传暂存（不进项目树）
└── <project>/
    ├── 成品/                    # 可发布产物
    ├── 素材/                    # 过程文件
    ├── .session/                # 🔒 系统：会话落盘
    └── .index.json              # 🔒 系统：产物索引
```

`artifacts` 表是**索引不是真相源**。文件被手动删了 → 列表扫描时自动剔除孤儿索引（并记一条日志，不静默）。

---

## 3. API 契约

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/library/projects` | 项目列表 + 每个项目的 成品/素材 计数 |
| `POST` | `/api/library/projects` | `{name}` → `paths.new_project()` |
| `GET` | `/api/library/tree?project=&zone=` | 目录树（面包屑 + 子项） |
| `GET` | `/api/library/files?project=&zone=&kind=&q=` | 文件列表（支持类型过滤 + 名称搜索） |
| `GET` | `/api/library/stream?path=` | ★ **Range 支持**，返回 206 / 200 |
| `GET` | `/api/library/meta?path=` | 文件元信息（size/mime/尺寸/时长） |
| `GET` | `/api/library/preview?path=` | 文本类（md/html/srt/json）返回内容供渲染 |
| `POST` | `/api/library/confirm-token` | `{path}` → `{token, expires_in}` （破坏性操作前置） |
| `DELETE` | `/api/library/file?path=&confirm=` | 单文件删除 |
| `DELETE` | `/api/library/project?project=&confirm=` | 整个项目删除（**必须显式声明「及其全部内容」**） |
| `POST` | `/api/library/unlock-system` | 解锁系统文件删除（需二次确认，M1 可先只给 UI 提示） |

**所有 `path` 参数都走 `paths.resolve_inside(OUTPUTS, path)`**，逃逸直接 400 `PathEscapeError`。

### 3.1 Range 流式（F-G6，硬要求）

```
GET /api/library/stream?path=outputs/a/成品/b.mp4
Range: bytes=0-1048575
→ 206 Partial Content
  Content-Range: bytes 0-1048575/18454912
  Content-Type: video/mp4
  Accept-Ranges: bytes
  Cache-Control: private, max-age=3600
```
- **必须正确处理** `Range`、`If-Range`、非法 Range（→ 416）
- 无 Range 时返回 200 + `Accept-Ranges: bytes`
- 大文件（> 50MB）必须走流式，不能 `read()` 进内存

### 3.2 删除保护（F-G7，硬要求）

| 情况 | 行为 |
|---|---|
| 删普通文件 | 弹窗文案必须含「**你正在删除 `card-01.png` 及其全部内容**」+ 要求输入文件名确认 |
| 删项目 | 弹窗列出项目内文件数与总大小，文案含「及其全部内容」 |
| 删系统文件 | **403 `SystemFileProtected`**，UI 提示「`.session/` 为系统文件，禁止删除」 |
| 路径逃逸 | 400 `PathEscapeError` |

---

## 4. 前端要点（`web/src/features/library/`）

照 `design/prototype-v1.html` 的 `#v-library`：

```
┌────────────┬─────────────────────────────────────────┐
│ 项目目录    │ [全部|图片|视频|音频|文档]  [▦|☰]        │
│ tool-dumb  │ ┌─────────────────────────────────────┐ │
│  成品 7    │ │ tool-dumb / 成品      [挂载到发布][删除]│ │
│  素材 3    │ │ ⚠️ 会话日志（.session/）受系统保护      │ │
│  .session 2│ │ ┌────┐ ┌────┐ ┌────┐ ┌────┐        │ │
│ agent-wf 9 │ │ │卡片│ │卡片│ │视频│ │字幕│        │ │
│  ...       │ │ └────┘ └────┘ └────┘ └────┘        │ │
└────────────┴─────────────────────────────────────────┘
┌──────────────────────────────────────────────────────┐
│ 预览 [sandbox iframe] [card-01.png]   1.2MB [原图][下载]│
└──────────────────────────────────────────────────────┘
```

组件：
- `ProjectTree.tsx` — 项目 → 成品/素材/.session；系统目录带「系统」chip 且置灰
- `FileGrid.tsx` / `FileList.tsx` — 两种视图
- `FileTile.tsx` — 缩略图 + 文件名 + 尺寸 + 大小
- `PreviewPane.tsx` — **按类型分派**：图片 `<img>` / 视频 `<video>` / 音频 `<audio>`+波形 / HTML `<iframe sandbox="">` / Markdown 渲染
- `DeleteDialog.tsx` — 输入文件名确认，文案显式声明后果
- `SystemFileNotice.tsx` — 顶部琥珀色提示条

**预览安全**：
- HTML → `<iframe sandbox src="...">`（`sandbox` 不给 `allow-same-origin`，杜绝读取宿主页面）
- 图片/视频/音频 → `src` 指向 `/api/library/stream?path=...`（走 Range）
- Markdown → 前端 `react-markdown` 渲染，**不注入原始 HTML**

---

## 5. 与其他域的衔接

| 来源 | 行为 |
|---|---|
| 对话里的产物路径 chip | 点击 → 切内容库 + 定位到该文件 + 滚动高亮 |
| 技能运行产出的文件 | 写入 artifacts 表 → 内容库立即可见 |
| 发布中心「从内容库挂载」 | 打开选择态 → 选文件 → 回填到草稿附件 |

---

## 6. 验收标准

| # | 标准 | 验证 |
|---|---|---|
| 1 | 产物按项目目录组织，成品/素材分区清晰 | 跑一个技能后看目录结构 |
| 2 | 面包屑逐级下钻 | 项目 → 成品 → 文件 |
| 3 | 类型过滤生效 | 选「视频」只剩视频 |
| 4 | 预览不等于发布，破坏性操作有二次确认 | 删文件必须输文件名 |
| 5 | 系统文件禁止删除 | 删 `.session/xxx` → 403 + 明确提示 |
| 6 | 大文件走 Range，不一次性加载 | curl 验证 206 + Content-Range |
| 7 | 路径逃逸被拦截 | 传 `../../etc/passwd` → 400 |
| 8 | 手动删文件后索引自动修正 | 终端删一个文件，刷新后列表不再显示 |
| 9 | 对话路径可点击直达 | 点路径 → 内容库定位 |

---

## 7. 测试清单

```python
# test_library.py（至少 9 个）
test_tree_lists_products_and_materials
test_range_request_returns_206
test_invalid_range_returns_416
test_path_escape_rejected              # ../ and symlink
test_symlink_escape_rejected
test_delete_requires_confirm_token
test_delete_system_file_403
test_delete_project_declares_all_content
test_orphan_index_cleaned_on_scan
test_html_preview_sandboxed
```
