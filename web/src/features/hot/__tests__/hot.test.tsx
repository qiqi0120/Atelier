/** SPEC-12 §6 · 热点发现页前端测试（M2-3b）。
 *
 * 覆盖：三 Tab 装配 · 诚实边界 notice · 素材池/订阅/算法三视图 ·
 * 手工导入请求体 · 存选题请求体（source=hot）· 日报 insufficient 空态 ·
 * BLOCK 改法展示。
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

import { HotPage } from '../HotPage'

const ENTRY = {
  id: 'hot-1',
  title: '热点一：平台调整图文流量规则',
  source: 'manual',
  platform: 'dy',
  url: '',
  heat: '榜3',
  note: '',
  entry_date: '2026-10-03',
  status: 'pending',
  digest_id: '',
  created_at: '2026-10-03T02:00:00',
  updated_at: '2026-10-03T02:00:00',
}

function emptyLists() {
  apiMock.get.mockImplementation((path: string) => {
    if (path.startsWith('/discovery/hot/digests')) return Promise.resolve({ items: [], total: 0 })
    if (path.startsWith('/discovery/hot'))
      return Promise.resolve({ items: [], total: 0, counts: { pending: 0, digested: 0, archived: 0 } })
    if (path.startsWith('/discovery/subscriptions')) return Promise.resolve({ items: [], total: 0 })
    if (path.startsWith('/discovery/feed')) return Promise.resolve({ items: [], total: 0, days: 7 })
    if (path.startsWith('/discovery/algorithm-notes'))
      return Promise.resolve({ items: [], total: 0, notice: '手工登记' })
    return Promise.reject(new Error(`unexpected GET ${path}`))
  })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/hot']}>
      <HotPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  apiMock.get.mockReset()
  apiMock.post.mockReset()
  apiMock.patch.mockReset()
  apiMock.del.mockReset()
})

describe('热点发现 · 页面装配与诚实边界', () => {
  it('渲染三 Tab、主行动与固定诚实 notice', async () => {
    emptyLists()
    renderPage()
    expect(screen.getByTestId('hot-notice')).toHaveTextContent('没有公开热点 API')
    await waitFor(() => expect(screen.getByRole('tab', { selected: true })).toHaveTextContent('素材池'))
    expect(screen.getByRole('button', { name: '生成日报' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /订阅源/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '算法追踪' })).toBeInTheDocument()
  })

  it('素材池空态给下一步动作', async () => {
    emptyLists()
    renderPage()
    expect(await screen.findByText('素材池还是空的')).toBeInTheDocument()
  })
})

describe('热点发现 · 素材池', () => {
  it('渲染条目并存选题（source=hot 可溯源）', async () => {
    const user = userEvent.setup()
    apiMock.get.mockImplementation((path: string) => {
      if (path.startsWith('/discovery/hot/digests')) return Promise.resolve({ items: [], total: 0 })
      if (path.startsWith('/discovery/hot'))
        return Promise.resolve({ items: [ENTRY], total: 1, counts: { pending: 1, digested: 0, archived: 0 } })
      if (path.startsWith('/discovery/subscriptions')) return Promise.resolve({ items: [], total: 0 })
      if (path.startsWith('/discovery/feed')) return Promise.resolve({ items: [], total: 0, days: 7 })
      if (path.startsWith('/discovery/algorithm-notes'))
        return Promise.resolve({ items: [], total: 0, notice: '手工登记' })
      return Promise.reject(new Error(`unexpected GET ${path}`))
    })
    apiMock.post.mockResolvedValueOnce({ id: 'topic-new', title: ENTRY.title })
    renderPage()
    const entry = await screen.findByTestId('hot-entry')
    expect(entry).toHaveTextContent('平台调整图文流量规则')
    await user.click(within(entry).getByRole('button', { name: /存选题/ }))
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        '/topics',
        expect.objectContaining({ source: 'hot', source_ref: `热点素材 ${ENTRY.entry_date}` }),
        expect.anything(),
      ),
    )
  })

  it('手工导入弹层发请求体', async () => {
    const user = userEvent.setup()
    emptyLists()
    apiMock.post.mockResolvedValueOnce({ id: 'hot-2' })
    renderPage()
    await user.click(await screen.findByRole('button', { name: /手工导入/ }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('热点标题 *'), '热点标题甲')
    await user.click(within(dialog).getByRole('button', { name: '导入' }))
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        '/discovery/hot',
        expect.objectContaining({ title: '热点标题甲' }),
        expect.anything(),
      ),
    )
  })
})

describe('热点发现 · 生成日报（诚实模式）', () => {
  it('素材池为空：insufficient 空态，不显示任何 markdown', async () => {
    const user = userEvent.setup()
    emptyLists()
    apiMock.post.mockResolvedValueOnce({
      insufficient: true,
      need: 1,
      stats: { pending: 0 },
      message: '素材池没有待处理的热点（pending=0）——先手工导入或从订阅转入，再生成日报，不编造热点',
    })
    renderPage()
    await user.click(await screen.findByRole('button', { name: '生成日报' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: '生成日报' }))
    expect(await within(dialog).findByText('素材池没有待处理的热点')).toBeInTheDocument()
    expect(within(dialog).queryByText('## 热点盘点')).not.toBeInTheDocument()
  })

  it('成功：渲染日报 markdown 并刷新素材池计数', async () => {
    const user = userEvent.setup()
    apiMock.get.mockImplementation((path: string) => {
      if (path.startsWith('/discovery/hot/digests')) return Promise.resolve({ items: [], total: 0 })
      if (path.startsWith('/discovery/hot'))
        return Promise.resolve({ items: [ENTRY], total: 1, counts: { pending: 1, digested: 0, archived: 0 } })
      if (path.startsWith('/discovery/subscriptions')) return Promise.resolve({ items: [], total: 0 })
      if (path.startsWith('/discovery/feed')) return Promise.resolve({ items: [], total: 0, days: 7 })
      if (path.startsWith('/discovery/algorithm-notes'))
        return Promise.resolve({ items: [], total: 0, notice: '手工登记' })
      return Promise.reject(new Error(`unexpected GET ${path}`))
    })
    apiMock.post.mockResolvedValueOnce({
      insufficient: false,
      digest: { id: 'd1', title: '日报', markdown: '正文', window_start: '', window_end: '', entry_ids: ['hot-1'], created_at: '' },
      markdown: '## 热点盘点\n\n素材甲已盘点。',
      sections: { 热点盘点: true, 机会点: true, 建议动作: true },
      entry_count: 1,
      gate_report: { blocked: false, items: [], failed: 0, warnings: 0 },
    })
    renderPage()
    await user.click(await screen.findByRole('button', { name: '生成日报' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: '生成日报' }))
    expect(await within(dialog).findByText('素材甲已盘点。')).toBeInTheDocument()
    expect(within(dialog).getByText(/已把 1 条素材标为「已进日报」/)).toBeInTheDocument()
  })

  it('门禁 BLOCK：弹层内展示改法', async () => {
    const user = userEvent.setup()
    emptyLists()
    apiMock.post.mockRejectedValueOnce(
      new ApiErrorMock(
        'GateBlocked',
        422,
        '热点日报未通过硬门禁：命中极限词',
        { gate_items: [{ gate: 'compliance', label: '合规', severity: 'block', passed: false, actual: '1 处', limit: '0 处', message: '命中极限词', fix_hint: '删掉「全网最好」这类词' }] },
        '把极限词删掉再重试',
      ),
    )
    renderPage()
    await user.click(await screen.findByRole('button', { name: '生成日报' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: '生成日报' }))
    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent('改法')
  })
})

describe('热点发现 · 订阅源', () => {
  it('切到订阅 Tab：空态引导新建', async () => {
    const user = userEvent.setup()
    emptyLists()
    renderPage()
    await user.click(await screen.findByRole('tab', { name: /订阅源/ }))
    expect(await screen.findByText('还没有订阅')).toBeInTheDocument()
  })

  it('新建订阅弹层发请求体（rss 必带 URL）', async () => {
    const user = userEvent.setup()
    emptyLists()
    apiMock.post.mockResolvedValueOnce({ id: 'sub-1' })
    renderPage()
    await user.click(await screen.findByRole('tab', { name: /订阅源/ }))
    await user.click(await screen.findByRole('button', { name: /新建订阅/ }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('名称 *'), '测试博主')
    await user.type(within(dialog).getByLabelText('RSS 地址 *'), 'https://example.com/rss')
    await user.click(within(dialog).getByRole('button', { name: '创建' }))
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        '/discovery/subscriptions',
        expect.objectContaining({ name: '测试博主', source: 'rss', url: 'https://example.com/rss' }),
        expect.anything(),
      ),
    )
  })
})

describe('热点发现 · 算法追踪', () => {
  it('空态 + 固定诚实标注', async () => {
    const user = userEvent.setup()
    emptyLists()
    renderPage()
    await user.click(await screen.findByRole('tab', { name: '算法追踪' }))
    expect(await screen.findByText('还没有登记')).toBeInTheDocument()
    expect(screen.getByText(/手工登记时间线/)).toBeInTheDocument()
  })
})
