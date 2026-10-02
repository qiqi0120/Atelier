# SPEC-07 · 前端外壳与设计系统

> 视觉规范以 `design/UI-SPEC.md` 为准（**唯一依据**），本文件只讲工程结构与落地方式。
> 原型参照：`design/prototype-v1.html`（13 页全部可交互，本批按原型 1:1 还原）。

## 1. 硬约束

| # | 约束 | 原因 |
|---|---|---|
| 1 | **禁止引入 Ant Design / MUI / Chakra 等 UI 框架** | 主题覆盖冲突、体积膨胀，视觉会跑偏 |
| 2 | 令牌写死在 `src/styles/tokens.css`，组件里**不许出现字面色值** | 改一处全站生效 |
| 3 | 图标只用 `lucide-react`，`strokeWidth={1.9}`，`currentColor` | 统一；禁止 emoji 当图标 |
| 4 | Markdown 一律 `react-markdown` + `remark-gfm`，**不注入原始 HTML** | XSS |
| 5 | HTML 预览走 `<iframe sandbox>`（不给 `allow-same-origin`） | 隔离 |
| 6 | 破坏性操作必须走 `ConfirmDialog` 组件 | 不允许在按钮上直接调 DELETE |
| 7 | 长列表（内容库/日历/评论）分页或虚拟滚动 | 性能 |
| 8 | 所有 API 走 `src/lib/api.ts` 一个 client | 统一错误处理 |

## 2. 目录

```
web/
├── index.html  vite.config.ts  tsconfig.json  package.json
└── src/
    ├── main.tsx
    ├── App.tsx                 # Router + 外壳布局
    ├── styles/
    │   ├── tokens.css          # ★ 设计令牌（UI-SPEC §2 原样搬）
    │   └── global.css          # reset + 基础排版 + 滚动条
    ├── components/             # 设计系统基础组件（各域共用）
    │   ├── Button.tsx  Chip.tsx  Card.tsx  Tabs.tsx  Badge.tsx
    │   ├── Input.tsx  Field.tsx  Select.tsx  Modal.tsx
    │   ├── Drawer.tsx  Toast.tsx  ConfirmDialog.tsx  EmptyState.tsx
    │   ├── Skeleton.tsx  Table.tsx  Avatar.tsx  ProgressBar.tsx
    │   └── index.ts
    ├── lib/
    │   ├── api.ts               # fetch 封装 + 统一错误 → toast
    │   ├── sse.ts               # SSE 客户端（自动重连 + 去重）
    │   ├── store.ts             # zustand：当前画像/会话/主题
    │   └── types.ts             # 对齐后端 Pydantic 模型
    ├── layout/
    │   ├── Sidebar.tsx          # 236px → 900px 收 60px
    │   ├── Topbar.tsx
    │   ├── ProfileSwitcher.tsx
    │   └── NavGroups.ts
    └── features/
        ├── workbench/ chat/ capability/ skills/ hot/ topics/
        ├── calendar/ library/ publish/ accounts/ analytics/
        ├── profile/ settings/
        └── <domain>/index.tsx  <Domain>Page.tsx  components/  api.ts
```

**M1 只做**：`workbench`(壳) `chat` `capability` `skills` `library` `publish` `profile` `settings`。
`hot` `topics` `calendar` `accounts` `analytics` 做成**占位页**（复用 `EmptyState` + 「M2 接入」说明），路由已注册。

## 3. 组件契约

统一 props 约定（各域组件照此写）：

```tsx
type ButtonProps = {
  variant?: 'primary' | 'default' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
  disabledReason?: string        // 禁用时必须说明原因（UI-SPEC 规则 3）
  icon?: LucideIcon
} & React.ButtonHTMLAttributes<HTMLButtonElement>
```

`Toast`：`useToast()` hook，全局挂在 `App`，右下角堆叠，成功/警告/普通三态。
`ConfirmDialog`：必须支持 `requireTyping?: string`（删文件时要求输入文件名，F-G7）。
`EmptyState`：**必须给出下一步动作**（标题 + 说明 + 一个按钮）。

## 4. `lib/api.ts` 约定

```ts
export class ApiError extends Error {
  code: string; http: number; detail?: unknown; hint?: string
}
async function request<T>(path: string, init?: RequestInit): Promise<T>
// 非 2xx → 抛 ApiError（解析后端 {error:{...}}）
// 204 → undefined
// 全局监听：ApiError 自动 toast（除非调用方声明 handled: true）
```

`sse.ts`：
```ts
export function createSSE(url, { onEvent, onError, onDone }): { close(): void }
// EventSource；onerror → 指数退避重连 0.5/1/2/4s，最多 5 次
// 重连成功后自动回调 onReconnect，供上层拉 /turn/{id} 补齐
```

## 5. 路由

| 路径 | 组件 | M1 |
|---|---|---|
| `/` | WorkbenchPage | ✅（占位数据） |
| `/chat` | ChatPage | ✅ |
| `/capability` | CapabilityPage | ✅ |
| `/skills` | SkillsPage | ✅ |
| `/library` | LibraryPage | ✅ |
| `/publish` | PublishPage | ✅ |
| `/profile` | ProfilePage | ✅ |
| `/settings` | SettingsPage | ✅ |
| `/hot` `/topics` `/calendar` `/accounts` `/analytics` | PlaceholderPage | 占位 |

## 6. 响应式

| 断点 | 行为 |
|---|---|
| > 900px | 侧栏 236px；对话页显示会话栏（216px） |
| ≤ 900px | 侧栏收 60px 只显图标；对话页隐藏会话栏（抽屉唤出）；网格 2 列 |
| ≤ 768px | 网格 1 列；日历格高 64px、事件 10px；**禁止横向滚动**（`overflow-x: hidden` + 弹性布局） |
| ≤ 560px | KPI 卡 1 列 |

## 7. 测试

| 层 | 要求 |
|---|---|
| 组件 | 每个基础组件至少 1 个渲染测试；`Button`（含 `disabledReason`）、`ConfirmDialog`（含 `requireTyping`）、`EmptyState` 必测 |
| feature | 每个域至少 3 个：渲染 / 关键交互 / 空态与错误态 |
| E2E | 冒烟脚本走一遍 SPEC-00 §3 的 M1 出口 8 条 |

## 8. 交付验收

1. `npm run build` 零 TS 错误、零 ESLint 警告
2. 13 个路由全部可访问，无白屏
3. 令牌文件里**搜不到**组件目录的硬编码色值（用 grep 自查）
4. 视窗缩到 375px 宽**无横向滚动条**
5. 页面视觉与 `prototype-v1.html` 逐页比对通过
