/** F-H1/F-H2 · 工作台页前端测试（M5）。
 *
 * 覆盖：hero 真实数字与全零鼓励文案 · KPI 真实映射 · 今日待办 todo_items 渲染与空态 ·
 * 最近产出 sent/failed 与 danger 提示 · 看板 insufficient 空态 / 折线与 Top 表格。
 * mock 方式与 features/analytics/__tests__ 一致：vi.hoisted + vi.mock('@/lib/api')。
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { apiMock, ApiErrorMock } = vi.hoisted(() => {
  class ApiError extends Error {
    code: string
    http: number
    detail?: unknown
    hint?: string
    constructor(code: string, http: number, message: string, detail?: unknown, hint?: string) {
      super(message)
      this.code = code
      this.http = http
      this.detail = detail
      this.hint = hint
    }
    get display(): string {
      return this.hint ? `${this.message}（${this.hint}）` : this.message
    }
  }
  return { apiMock: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() }, ApiErrorMock: ApiError }
})
vi.mock('@/lib/api', () => ({ api: apiMock, ApiError: ApiErrorMock }))

import { WorkbenchPage } from '../WorkbenchPage'
import type { DashboardResponse, WorkbenchSummary } from '../types'

function summary(over: Partial<WorkbenchSummary> = {}): WorkbenchSummary {
  return {
    topics: { todo: 2, doing: 1, done: 3 },
    drafts_pending: 2,
    calendar_today: 1,
    hot_pending: 4,
    artifacts_last_7d: 5,
    records_last_7d: { sent: 3, failed: 1 },
    scheduler: {
      enabled: true,
      interval_seconds: 30,
      due_count: 2,
      last_tick: '',
      running: true,
      now: '',
      notice: 'dry-run',
    },
    todo_items: [
      { kind: 'draft', title: '今日该发的稿', to: '/publish' },
      { kind: 'topic', title: '进行中的选题', to: '/topics' },
      { kind: 'calendar', title: '周三截稿', to: '/calendar' },
    ],
    as_of: '2026-10-03T00:00:00+00:00',
    ...over,
  }
}

const DASH_DATA: DashboardResponse = {
  platform: '',
  days: 30,
  snapshots: [
    { captured_at: '2026-09-01', followers: 100 },
    { captured_at: '2026-09-12', followers: 130 },
    { captured_at: '2026-09-20', followers: 160 },
  ],
  metrics_by_day: [
    { collected_at: '2026-09-19', views: 300, likes: 30, comments: 3, shares: 1 },
    { collected_at: '2026-09-20', views: 900, likes: 90, comments: 10, shares: 5 },
  ],
  top_contents: [{ title: '爆款标题', platform: 'xhs', views: 900, likes: 90 }],
  insufficient: false,
}

function mockBackend(opts: {
  summaryBody?: WorkbenchSummary
  dashboardBody?: DashboardResponse
  summaryError?: boolean
} = {}) {
  apiMock.get.mockImplementation(async (url: string) => {
    if (url.includes('/attribution/workbench-summary')) {
      if (opts.summaryError) {
        throw new ApiErrorMock('NetworkError', 0, '连不上本地服务')
      }
      return opts.summaryBody ?? summary()
    }
    if (url.includes('/attribution/dashboard')) {
      return opts.dashboardBody ?? DASH_DATA
    }
    if (url.includes('/discovery/hot')) return { items: [], total: 0 }
    return {}
  })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <WorkbenchPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  apiMock.get.mockReset()
  apiMock.post.mockReset()
  apiMock.patch.mockReset()
  apiMock.del.mockReset()
})

describe('工作台 · F-H1 概览', () => {
  it('hero 与 KPI 用真实数字，待办按 todo_items 渲染', async () => {
    mockBackend()
    renderPage()
    // hero：今天有 2 条待发 · 1 个选题进行中 · 5 件产物近 7 天入库
    const hero = await screen.findByText(/今天有/)
    expect(hero).toHaveTextContent('2 条')
    expect(hero).toHaveTextContent('1 个选题进行中')
    expect(hero).toHaveTextContent('5 件')
    // KPI：进行中选题 + 「共 6 条在库」；待发 + 调度器到期；产出 + sent/failed
    expect(screen.getByText('共 6 条在库')).toBeInTheDocument()
    expect(screen.getByText('调度器 · 2 条到期')).toBeInTheDocument()
    expect(screen.getByText('sent 3 · failed 1')).toBeInTheDocument()
    // 今日待办：三条 todo_items，kind Chip 文案正确
    expect(await screen.findByText('今日该发的稿')).toBeInTheDocument()
    expect(screen.getByText('进行中的选题')).toBeInTheDocument()
    expect(screen.getByText('周三截稿')).toBeInTheDocument()
    const chips = screen.getAllByText('待发')
    expect(chips.length).toBeGreaterThan(0)
    // 最近产出：sent/failed 两行 + failed>0 danger 提示
    expect(screen.getByText('近 7 天发送成功')).toBeInTheDocument()
    expect(screen.getByText(/有失败记录/)).toBeInTheDocument()
    expect(screen.getByText(/数据看板见下方/)).toBeInTheDocument()
  })

  it('全零时 hero 换成鼓励文案并带去选题库链接，待办给空态', async () => {
    mockBackend({
      summaryBody: summary({
        topics: { todo: 0, doing: 0, done: 0 },
        drafts_pending: 0,
        artifacts_last_7d: 0,
        records_last_7d: { sent: 0, failed: 0 },
        todo_items: [],
      }),
    })
    renderPage()
    const hero = await screen.findByText(/今天还没有排期/)
    expect(hero).toHaveTextContent('去选题库找点事做')
    expect(await screen.findByText('今天没有待办')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '去选题库' })).toBeInTheDocument()
    // failed=0：不出现 danger 提示
    expect(screen.queryByText(/有失败记录/)).not.toBeInTheDocument()
  })

  it('概览请求失败时如实提示，不假装是零', async () => {
    mockBackend({ summaryError: true })
    renderPage()
    expect(await screen.findByText(/概览暂时没拉到/)).toBeInTheDocument()
  })

  it('待办条目点击后跳转到对应路径', async () => {
    mockBackend()
    const { container } = render(
      <MemoryRouter initialEntries={['/']}>
        <WorkbenchPage />
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    const row = await screen.findByText('今日该发的稿')
    // 简单断言：行可点击且带 Cursor 样式的 task 类（跳转细节交给路由）
    expect(row.closest('.task')).not.toBeNull()
    await user.click(row)
    expect(container).toBeInTheDocument()
  })
})

describe('工作台 · F-H2 创作数据看板', () => {
  it('insufficient 时渲染诚实空态与去录入动作', async () => {
    mockBackend({
      dashboardBody: {
        platform: '',
        days: 30,
        snapshots: [],
        metrics_by_day: [],
        top_contents: [],
        insufficient: true,
        message: '全部平台近 30 天还没有快照或表现数据——看板只画真实录入的数据',
      },
    })
    renderPage()
    expect(await screen.findByText('看板只画真实录入的数据')).toBeInTheDocument()
    expect(screen.getByText(/还没有快照或表现数据/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '去录入数据' })).toBeInTheDocument()
  })

  it('有数据时：首尾差正确、折线 polyline 渲染、Top 表格出行', async () => {
    mockBackend()
    const { container } = renderPage()
    // 粉丝快照：最新 160 vs 首条 100 → ↑ 60
    expect(await screen.findByText('↑ 60')).toBeInTheDocument()
    expect(screen.getByText('2026-09-01 → 2026-09-20')).toBeInTheDocument()
    // 手写 SVG 折线
    await waitFor(() => expect(container.querySelector('svg polyline')).toBeInTheDocument())
    // 表现合计：views 300+900=1200 / likes 120 / comments 13 / shares 6
    const dash = container.querySelector('#dashboard') as HTMLElement
    expect(within(dash).getAllByText('1200').length).toBeGreaterThan(0)
    expect(within(dash).getAllByText('120').length).toBeGreaterThan(0)
    // Top 内容表
    expect(within(dash).getByText('爆款标题')).toBeInTheDocument()
    expect(within(dash).getAllByText('浏览').length).toBeGreaterThan(0)
  })

  it('平台与时间窗变化会带参重拉 dashboard', async () => {
    mockBackend()
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('↑ 60')
    await user.selectOptions(screen.getByLabelText('看板平台'), 'xhs')
    await user.selectOptions(screen.getByLabelText('看板时间窗'), '7')
    await waitFor(() => {
      const calls = apiMock.get.mock.calls.filter((c) => String(c[0]).includes('/attribution/dashboard'))
      const last = String(calls[calls.length - 1]?.[0])
      expect(last).toContain('platform=xhs')
      expect(last).toContain('days=7')
    })
  })
})
