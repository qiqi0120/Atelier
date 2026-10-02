/** SPEC-09 §8 · 日历页前端测试（M2-2 前半）。
 *
 * 覆盖：月视图装配（节点斜纹 / 选题条目跳转）· 新建事件 · 删除二次确认 ·
 * 导入本年节点 · 建议弹层参数与结果渲染 · 提醒徽标文案 · 月份切换。
 * api 走与真实 ApiError 同形的替身（同 topics 测试模式）。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
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

import { CalendarPage } from '../CalendarPage'
import type { CalEvent, MonthView, UpcomingResponse } from '../types'

const pad = (n: number) => String(n).padStart(2, '0')

/** 与页面同口径取「当前月」，测试数据永远落在正在看的这个月里 */
function currentMonth(): string {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`
}

function event(over: Partial<CalEvent> = {}): CalEvent {
  return {
    id: 'event-1',
    title: '双11',
    date: `${currentMonth()}-11`,
    end_date: '',
    kind: 'ecommerce',
    note: '',
    remind_days: 3,
    source: 'builtin',
    created_at: '2026-10-02T10:00:00+00:00',
    updated_at: '2026-10-02T10:00:00+00:00',
    ...over,
  }
}

const MONTH = (month: string): MonthView => ({
  month,
  events: [
    event(),
    event({ id: 'event-2', title: '品牌发布会', date: `${month}-20`, kind: 'platform', source: 'manual' }),
  ],
  topics: [
    {
      id: 'topic-1',
      profile_id: null,
      title: '双11 开箱：300 元内好物实测',
      angle: '',
      source: 'calendar',
      source_ref: '双11',
      status: 'todo',
      decode: '',
      due_date: `${month}-09`,
      stage: 'topic',
      draft_id: null,
      created_at: '2026-10-02T10:00:00+00:00',
      updated_at: '2026-10-02T10:00:00+00:00',
    },
  ],
  drafts: [],
})

const UPCOMING: UpcomingResponse = {
  today: '2026-10-03',
  items: [
    { ...event({ id: 'u1', date: `${currentMonth()}-03` }), remind_active: true, days_left: 0 },
    { ...event({ id: 'u2', title: '品牌发布会', date: `${currentMonth()}-20` }), remind_active: false, days_left: 8 },
  ],
}

function mockData(month = currentMonth()) {
  apiMock.get.mockImplementation(async (url: string) => {
    if (url.startsWith('/calendar/upcoming')) return UPCOMING
    if (url.startsWith('/calendar')) return MONTH(month)
    throw new Error('unexpected GET ' + url)
  })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/calendar']}>
      <Routes>
        <Route path="/calendar" element={<CalendarPage />} />
        <Route path="/topics" element={<div>选题库页</div>} />
        <Route path="/publish" element={<div>发布中心页</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  apiMock.get.mockReset()
  apiMock.post.mockReset()
  apiMock.patch.mockReset()
  apiMock.del.mockReset()
  apiMock.post.mockResolvedValue({})
  apiMock.patch.mockResolvedValue({})
  apiMock.del.mockResolvedValue({ ok: true, id: 'event-1' })
  mockData()
})

describe('内容日历 · 月视图装配', () => {
  it('渲染月头、节点条目与选题条目；平台活动/事件用斜纹 act，选题不用', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByTestId('cal-grid')).toBeInTheDocument())
    expect(screen.getByTestId('month-label')).toHaveTextContent(/年\d+月/)
    const promo = screen.getByTitle(/电商节点 · 双11/)
    expect(promo).toHaveClass('act')
    const platform = screen.getByTitle(/平台活动 · 品牌发布会/)
    expect(platform).toHaveClass('act')
    const topic = screen.getByTitle(/选题 · 双11 开箱：300 元内好物实测/)
    expect(topic).not.toHaveClass('act')
  })

  it('点击选题条目跳转 /topics', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByTestId('cal-grid')).toBeInTheDocument())
    fireEvent.click(screen.getByTitle(/选题 · 双11 开箱/))
    expect(screen.getByText('选题库页')).toBeInTheDocument()
  })

  it('近 14 天节点条：提醒期内 accent，文案区分 今天 / 还有 N 天', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByTestId('upcoming-strip')).toBeInTheDocument())
    expect(screen.getByText(/双11 · 今天/)).toBeInTheDocument()
    expect(screen.getByText(/品牌发布会 · 还有 8 天/)).toBeInTheDocument()
  })

  it('月份切换：上一个月 / 本月', async () => {
    const user = userEvent.setup()
    renderPage()
    const label = await screen.findByTestId('month-label')
    const before = label.textContent
    await user.click(screen.getByRole('button', { name: '上一个月' }))
    expect(screen.getByTestId('month-label').textContent).not.toBe(before)
    await user.click(screen.getByRole('button', { name: '本月' }))
    await waitFor(() => expect(screen.getByTestId('month-label').textContent).toBe(before))
  })
})

describe('内容日历 · 新建与删除', () => {
  it('新建事件：填名称与日期后提交 POST /calendar', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByRole('button', { name: '新建事件' }))
    await user.type(screen.getByLabelText(/名称/), '品牌快闪活动')
    fireEvent.change(screen.getByLabelText(/开始日期/), { target: { value: `${currentMonth()}-21` } })
    await user.click(screen.getByRole('button', { name: '创建' }))
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        '/calendar',
        expect.objectContaining({ title: '品牌快闪活动', date: `${currentMonth()}-21`, kind: 'festival' }),
        expect.anything(),
      ),
    )
  })

  it('编辑弹层的删除走二次确认（UI-SPEC 规则 19）', async () => {
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => expect(screen.getByTestId('cal-grid')).toBeInTheDocument())
    await user.click(screen.getByTitle(/电商节点 · 双11/))
    await user.click(await screen.findByRole('button', { name: /删除/ }))
    expect(screen.getByText('删除这个节点？')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '删除节点' }))
    await waitFor(() => expect(apiMock.del).toHaveBeenCalledWith('/calendar/event-1', expect.anything()))
  })
})

describe('内容日历 · 工具条动作', () => {
  it('导入本年节点：POST /calendar/seed 且提示导入数量', async () => {
    const user = userEvent.setup()
    apiMock.post.mockResolvedValueOnce({ year: 2026, added: 15, skipped: 0 })
    renderPage()
    await user.click(await screen.findByRole('button', { name: '导入本年节点' }))
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/calendar/seed', {}, expect.anything()))
  })

  it('生成建议：默认窗口 14 天提交，结果渲染条目数与标题', async () => {
    const user = userEvent.setup()
    apiMock.post.mockResolvedValueOnce({
      count: 2,
      items: [
        { id: 'topic-9', due_date: `${currentMonth()}-09`, title: '建议甲' },
        { id: 'topic-10', due_date: `${currentMonth()}-12`, title: '建议乙' },
      ],
    })
    renderPage()
    await user.click(await screen.findByRole('button', { name: '生成近 14 天建议' }))
    await user.click(screen.getByRole('button', { name: '生成建议' }))
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        '/calendar/suggest',
        expect.objectContaining({ days: 14 }),
        expect.anything(),
      ),
    )
    expect(screen.getByText(/已入库/)).toBeInTheDocument()
    expect(screen.getByText('建议甲')).toBeInTheDocument()
    expect(screen.getByText('建议乙')).toBeInTheDocument()
  })
})

describe('内容日历 · 状态流转（SPEC-10 §3）', () => {
  function mockLifecycle() {
    const month = currentMonth()
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/calendar/upcoming')) return UPCOMING
      return {
        month,
        events: [],
        topics: [
          {
            id: 'topic-1',
            profile_id: null,
            title: '双11 开箱：300 元内好物实测',
            angle: '',
            source: 'calendar',
            source_ref: '双11',
            status: 'todo',
            decode: '',
            due_date: `${month}-09`,
            stage: 'ready',
            draft_id: 'pd1',
            created_at: '2026-10-02T10:00:00+00:00',
            updated_at: '2026-10-02T10:00:00+00:00',
          },
        ],
        drafts: [
          {
            id: 'pd1',
            title: '排期草稿',
            scheduled_date: `${month}-20`,
            topic_id: 'topic-1',
            topic_title: '双11 开箱：300 元内好物实测',
            stage: 'ready',
          },
        ],
      }
    })
  }

  it('选题条目带待发徽标；排期草稿条目可溯源到选题；点击分流到 /publish', async () => {
    const user = userEvent.setup()
    mockLifecycle()
    renderPage()
    await waitFor(() => expect(screen.getByTestId('cal-grid')).toBeInTheDocument())
    const ready = screen.getByTitle(/选题 · 双11 开箱：300 元内好物实测（待发）/)
    expect(ready).toHaveTextContent('⟨待发⟩')
    const draftEv = screen.getByTitle(/草稿 · 排期草稿（选题：双11 开箱：300 元内好物实测）/)
    expect(draftEv).toHaveTextContent('⟨待发⟩')
    await user.click(ready)
    expect(screen.getByText('发布中心页')).toBeInTheDocument()
  })

  it('stage=topic 的选题条目仍去 /topics（回归）', async () => {
    const user = userEvent.setup()
    mockData()
    renderPage()
    await waitFor(() => expect(screen.getByTestId('cal-grid')).toBeInTheDocument())
    await user.click(screen.getByTitle(/选题 · 双11 开箱：300 元内好物实测/))
    expect(screen.getByText('选题库页')).toBeInTheDocument()
  })
})
