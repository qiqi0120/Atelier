/** SPEC-04 §5 · 能力地图页前端测试（静态硬编码目录 → GET /api/capabilities 改造回归）。
 *
 * 覆盖：分组/条目渲染与成熟度 Chip · F-C4 点击填入（fillPrompt + navigate，不自动发送）·
 * 搜索过滤与空态 · 后端分组为空的 EmptyState 引导 · 加载失败静态条 + 重试。
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { apiMock, ApiErrorMock, fillPromptMock } = vi.hoisted(() => {
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
  return {
    apiMock: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
    ApiErrorMock: ApiError,
    fillPromptMock: vi.fn(),
  }
})
vi.mock('@/lib/api', () => ({ api: apiMock, ApiError: ApiErrorMock }))

// store 只需要 profile=null 与 fillPrompt spy（能力页不读画像）
vi.mock('@/lib/store', async () => {
  const { create } = await vi.importActual<typeof import('zustand')>('zustand')
  const useAtelier = create(() => ({
    profile: null,
    profiles: [],
    memories: [],
    sessionId: null,
    draftPrompt: '',
    draftSeq: 0,
    setProfile: vi.fn(),
    setProfiles: vi.fn(),
    setMemories: vi.fn(),
    setSessionId: vi.fn(),
    fillPrompt: fillPromptMock,
    clearPrompt: vi.fn(),
  }))
  return { useAtelier }
})

import { CapabilityPage } from '../CapabilityPage'

const CAPS = {
  groups: [
    {
      name: '做内容 · 要成品',
      desc: '给一句主题，产出能直接发的东西',
      items: [
        {
          id: 'xhs-card', group: '做内容 · 要成品', name: '小红书知识卡',
          trigger: '当你说「做成小红书图文」时使用', maturity: 'v0', skill_id: 'xhs-card',
          outputs: ['image'], paid: false, required_keys: [], has_script: true, icon: 'layout',
        },
        {
          id: 'aigc-img', group: '做内容 · 要成品', name: 'AI 生图',
          trigger: '当你说「配图」时使用', maturity: 'v2', skill_id: 'aigc-img',
          outputs: ['image'], paid: true, required_keys: ['MINIMAX_API_KEY'], has_script: true, icon: 'image',
        },
      ],
    },
    {
      name: '做运营 · 要动作',
      desc: '把「今天发什么」变成明确的下一步',
      items: [
        {
          id: 'hot', group: '做运营 · 要动作', name: '今日热榜聚合',
          trigger: '当你说「今天有什么热点」时使用', maturity: 'v0', skill_id: 'hot',
          outputs: ['markdown'], paid: false, required_keys: [], has_script: true, icon: 'flame',
        },
      ],
    },
  ],
  dead_links: [],
  total: 3,
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/capability']}>
      <Routes>
        <Route path="/capability" element={<CapabilityPage />} />
        <Route path="/chat" element={<div>对话工作台</div>} />
        <Route path="/skills" element={<div>技能库</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  apiMock.get.mockReset()
  apiMock.post.mockReset()
  apiMock.patch.mockReset()
  apiMock.del.mockReset()
  fillPromptMock.mockClear()
  apiMock.get.mockResolvedValue(CAPS)
})

describe('能力地图 · 分组渲染', () => {
  it('按 GET /api/capabilities 渲染分组、条目与成熟度 Chip', async () => {
    renderPage()
    expect(await screen.findByText('做内容 · 要成品')).toBeInTheDocument()
    expect(screen.getByText('给一句主题，产出能直接发的东西')).toBeInTheDocument()
    expect(screen.getByText('小红书知识卡')).toBeInTheDocument()
    expect(screen.getByText('今日热榜聚合')).toBeInTheDocument()
    // 成熟度 Chip（MATURITY_LABEL）；「需配置」也出现在筛选 Tab 上，用类名限定
    expect(screen.getAllByText('已验证').length).toBe(2)
    expect(screen.getByText('需配置', { selector: '.mature' })).toBeInTheDocument()
    // 分组小节计数来自条目数
    expect(screen.getByText('2 项能力')).toBeInTheDocument()
    expect(screen.getByText('1 项能力')).toBeInTheDocument()
    // 底部合计来自 total
    expect(screen.getByText(/共 3 项能力/)).toBeInTheDocument()
  })
})

describe('能力地图 · F-C4 点击填入', () => {
  it('点能力项 → fillPrompt(触发语) → 跳 /chat，不自动发送', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByText('小红书知识卡'))
    expect(fillPromptMock).toHaveBeenCalledTimes(1)
    expect(fillPromptMock).toHaveBeenCalledWith('当你说「做成小红书图文」时使用')
    await waitFor(() => expect(screen.getByText('对话工作台')).toBeInTheDocument())
  })
})

describe('能力地图 · 搜索过滤', () => {
  it('按名称过滤条目；全不匹配给空态并可一键清空', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('小红书知识卡')
    const box = screen.getByLabelText('搜索能力名')
    await user.type(box, '热榜')
    expect(screen.queryByText('小红书知识卡')).not.toBeInTheDocument()
    expect(screen.getByText('今日热榜聚合')).toBeInTheDocument()

    await user.clear(box)
    await user.type(box, '不存在的词')
    expect(await screen.findByText(/没有匹配「不存在的词」的能力/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '清空搜索' }))
    expect(await screen.findByText('小红书知识卡')).toBeInTheDocument()
  })
})

describe('能力地图 · 空态与错误态', () => {
  it('后端分组为空：EmptyState 引导去技能库', async () => {
    const user = userEvent.setup()
    apiMock.get.mockResolvedValue({ groups: [], dead_links: [], total: 0 })
    renderPage()
    expect(await screen.findByText('能力地图还是空的')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '去技能库' }))
    await waitFor(() => expect(screen.getByText('技能库')).toBeInTheDocument())
  })

  it('加载失败：role=alert 静态条 + 重试成功后渲染数据', async () => {
    const user = userEvent.setup()
    apiMock.get.mockRejectedValue(
      new ApiErrorMock('NetworkError', 0, '连不上本地服务', undefined, '确认后端已在 127.0.0.1:8000 运行'),
    )
    renderPage()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('连不上本地服务')
    apiMock.get.mockResolvedValue(CAPS)
    await user.click(within(alert.parentElement as HTMLElement).getByRole('button', { name: '重试' }))
    expect(await screen.findByText('小红书知识卡')).toBeInTheDocument()
  })
})
