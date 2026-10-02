/** SPEC-04 §5 · 技能库页前端测试（静态硬编码 SKILLS → GET /api/skills 改造回归）。
 *
 * 覆盖：列表渲染 + 层计数 · F-C10 缺钥禁用（! 角标 + 运行禁用原因）·
 * F-C7 详情抽屉 markdown + 参数默认值 · F-C8 就地运行（轮询 → 结果/产物）·
 * cost_pending 费用确认流（confirm_cost 重发）· 搜索客户端过滤 · F-C9 密钥留空不提交。
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ActiveProfile } from '@/lib/store'

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

// profile=null → run 请求不带 profile_id；fillPrompt spy 备用
vi.mock('@/lib/store', async () => {
  const { create } = await vi.importActual<typeof import('zustand')>('zustand')
  const useAtelier = create<{ profile: ActiveProfile | null; fillPrompt: (t: string) => void }>(() => ({
    profile: null,
    fillPrompt: fillPromptMock,
  }))
  return { useAtelier }
})

import { SkillsPage } from '../SkillsPage'

const FREE = {
  id: 'xhs-card', name: '小红书知识卡', layer: '制作', maturity: 'v0',
  trigger: '当你说「做成小红书图文」时使用', cost: '本地 · 免费',
  required_keys: [] as string[],
  params: [
    { key: 'title', label: '标题', default: 'AI 工具越用越笨' },
    { key: 'count', label: '张数', default: '3' },
  ],
  outputs: ['image'], paid: false, script: 'run.py', missing_keys: [] as string[], runnable: true,
}

const PLANNER = {
  id: 'viral-decode', name: '爆款拆解', layer: '策划', maturity: 'v0',
  trigger: '当你说「拆一下这条爆款」时使用', cost: '本地 · 免费',
  required_keys: [] as string[],
  params: [] as { key: string; label: string; default: string }[],
  outputs: ['markdown'], paid: false, script: null, missing_keys: [] as string[], runnable: true,
}

const PAID = {
  id: 'one-video', name: '一键成片', layer: '制作', maturity: 'v2',
  trigger: '当你说「一键成片」时使用', cost: '按量计费 · 需密钥',
  required_keys: ['MINIMAX_API_KEY'],
  params: [{ key: 'topic', label: '主题', default: '' }],
  outputs: ['video'], paid: true, script: null,
  missing_keys: ['MINIMAX_API_KEY'], runnable: false,
}

const FREE_BODY = '# 小红书知识卡\n\n把一段内容拆成 **3–9 张竖版卡片**。\n\n## 硬门禁\n\n- 尺寸 1080×1440'
const PAID_BODY = '# 一键成片\n\n**付费操作**：先给费用预估，确认后才执行。'

const DETAIL_FREE = { ...FREE, body_markdown: FREE_BODY, block_reason: null }
const DETAIL_PAID = { ...PAID, body_markdown: PAID_BODY, block_reason: '缺少 MINIMAX_API_KEY，运行已禁用' }

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/skills']}>
      <SkillsPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  apiMock.get.mockReset()
  apiMock.post.mockReset()
  apiMock.patch.mockReset()
  apiMock.del.mockReset()
  fillPromptMock.mockClear()
  apiMock.get.mockImplementation(async (url: string) => {
    if (url === '/skills') return { skills: [FREE, PLANNER, PAID], count: 3, layers: ['策划', '制作'] }
    if (url.startsWith('/skills/runs?')) return { runs: [] }
    if (url === '/skills/xhs-card') return DETAIL_FREE
    if (url === '/skills/one-video') return DETAIL_PAID
    return {}
  })
})

async function openDrawer(name: string) {
  const user = userEvent.setup()
  renderPage()
  const card = (await screen.findByText(name)).closest('.sk')
  expect(card).not.toBeNull()
  await user.click(within(card as HTMLElement).getByRole('button', { name: '详情 / 运行' }))
  const dialog = await screen.findByRole('dialog', { name })
  return { user, dialog, card: card as HTMLElement }
}

describe('技能库 · 列表与层计数', () => {
  it('列表来自 GET /api/skills，层 Tab 带真实计数', async () => {
    renderPage()
    expect(await screen.findByText('小红书知识卡')).toBeInTheDocument()
    expect(screen.getByText('爆款拆解')).toBeInTheDocument()
    expect(screen.getByText('一键成片')).toBeInTheDocument()
    const tablist = screen.getByRole('tablist', { name: '技能层' })
    expect(tablist).toHaveTextContent('全部 3')
    expect(tablist).toHaveTextContent('策划 1')
    expect(tablist).toHaveTextContent('制作 2')
    // 分组小节 + 底部合计来自 count
    expect(screen.getByText('制作层技能')).toBeInTheDocument()
    expect(screen.getByText('策划层技能')).toBeInTheDocument()
    expect(screen.getByText(/技能库共 3 个技能/)).toBeInTheDocument()
  })

  it('搜索为客户端过滤 name/trigger', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('小红书知识卡')
    await user.type(screen.getByLabelText('搜索技能'), '爆款')
    expect(screen.queryByText('小红书知识卡')).not.toBeInTheDocument()
    expect(screen.getByText('爆款拆解')).toBeInTheDocument()
  })
})

describe('技能库 · F-C10 缺钥禁用', () => {
  it('缺钥技能：卡片带 ! 角标，抽屉运行按钮禁用并说明原因', async () => {
    const { dialog, card } = await openDrawer('一键成片')
    // 卡片角标（Badge）：页头说明里也有一个 !，限定在缺钥卡片内断言
    expect(within(card).getByText('!')).toBeInTheDocument()
    // 抽屉内缺钥原因（正文提示 + 禁用按钮 tooltip 都会出现）+ 禁用的主行动按钮
    expect(
      (await within(dialog).findAllByText('缺少 MINIMAX_API_KEY，运行已禁用')).length,
    ).toBeGreaterThan(0)
    const runBtn = await within(dialog).findByRole('button', { name: '运行' })
    expect(runBtn).toBeDisabled()
    expect(runBtn.closest('.btn-wrap')).toHaveAttribute(
      'aria-label',
      '禁用原因：缺少 MINIMAX_API_KEY，运行已禁用',
    )
    // API 配置表单出现（F-C9）
    expect(within(dialog).getByLabelText('MINIMAX_API_KEY')).toBeInTheDocument()
  })
})

describe('技能库 · F-C7 详情抽屉', () => {
  it('渲染 SKILL.md 全文（ReactMarkdown）与参数表单默认值', async () => {
    const { dialog } = await openDrawer('小红书知识卡')
    expect(await within(dialog).findByRole('heading', { name: '硬门禁' })).toBeInTheDocument()
    expect(within(dialog).getByText(/3–9 张竖版卡片/)).toBeInTheDocument()
    expect(within(dialog).getByLabelText('标题')).toHaveValue('AI 工具越用越笨')
    expect(within(dialog).getByLabelText('张数')).toHaveValue('3')
  })
})

describe('技能库 · F-C8 就地运行', () => {
  it('提交后轮询，完成后渲染 result_markdown 与产物列表', async () => {
    const user = userEvent.setup()
    let polls = 0
    apiMock.get.mockImplementation(async (url: string) => {
      if (url === '/skills') return { skills: [FREE], count: 1, layers: ['制作'] }
      if (url.startsWith('/skills/runs?')) return { runs: [] }
      if (url === '/skills/runs/r1') {
        polls += 1
        return polls >= 2
          ? {
              run_id: 'r1', skill_id: 'xhs-card', status: 'done',
              result_markdown: '已生成 2 张卡片（1080×1440）', duration: 2.31, cost_actual: 0,
              artifacts: [{ path: 'outputs/default/成品/xhs-card/01.png', name: '01.png', kind: 'image' }],
              error: null,
            }
          : { run_id: 'r1', skill_id: 'xhs-card', status: 'running', result_markdown: '', artifacts: [] }
      }
      if (url === '/skills/xhs-card') return DETAIL_FREE
      return {}
    })
    apiMock.post.mockResolvedValueOnce({
      run_id: 'r1', skill_id: 'xhs-card', status: 'running', stream_url: '/api/skills/runs/r1',
    })
    renderPage()
    const card = (await screen.findByText('小红书知识卡')).closest('.sk') as HTMLElement
    await user.click(within(card).getByRole('button', { name: '详情 / 运行' }))
    const dialog = await screen.findByRole('dialog', { name: '小红书知识卡' })
    await user.click(await within(dialog).findByRole('button', { name: '运行' }))
    expect(apiMock.post).toHaveBeenCalledWith(
      '/skills/xhs-card/run',
      expect.objectContaining({ params: { title: 'AI 工具越用越笨', count: '3' }, confirm_cost: false }),
      expect.anything(),
    )
    // 轮询 1.5s 一次，放宽等待窗口
    expect(
      await within(dialog).findByText('已生成 2 张卡片（1080×1440）', {}, { timeout: 6000 }),
    ).toBeInTheDocument()
    expect(within(dialog).getByText('01.png')).toBeInTheDocument()
    expect(within(dialog).getByText('outputs/default/成品/xhs-card/01.png')).toBeInTheDocument()
    expect(within(dialog).getByText('image')).toBeInTheDocument()
  })

  it('付费技能：cost_pending 先弹费用确认，确认后带 confirm_cost=true 重发', async () => {
    const user = userEvent.setup()
    const paidRunnable = { ...PAID, missing_keys: [], runnable: true }
    apiMock.get.mockImplementation(async (url: string) => {
      if (url === '/skills') return { skills: [paidRunnable], count: 1, layers: ['制作'] }
      if (url.startsWith('/skills/runs?')) return { runs: [] }
      if (url === '/skills/runs/r1')
        return { run_id: 'r1', skill_id: 'one-video', status: 'running', result_markdown: '', artifacts: [] }
      if (url === '/skills/one-video') return { ...paidRunnable, body_markdown: PAID_BODY, block_reason: null }
      return {}
    })
    apiMock.post.mockResolvedValueOnce({
      run_id: 'r0', skill_id: 'one-video', status: 'cost_pending', requires_confirm: true, paid: true,
      cost_estimate: {
        currency: 'CNY', amount: 23.4, note: '确认后才开始计费',
        breakdown: [
          { label: '视频生成', qty: 45, rate: 0.5, amount: 22.5 },
          { label: '配音', qty: 45, rate: 0.02, amount: 0.9 },
        ],
      },
      result_markdown: '本次预计消耗 ¥23.40。点「取消」不产生任何费用。',
      artifacts: [], cost_actual: 0, error: null,
    })
    apiMock.post.mockResolvedValueOnce({
      run_id: 'r1', skill_id: 'one-video', status: 'running', stream_url: '/api/skills/runs/r1',
    })
    renderPage()
    const card = (await screen.findByText('一键成片')).closest('.sk') as HTMLElement
    await user.click(within(card).getByRole('button', { name: '详情 / 运行' }))
    const drawer = await screen.findByRole('dialog', { name: '一键成片' })
    await user.click(await within(drawer).findByRole('button', { name: '运行' }))

    // 费用确认 Modal：金额 + breakdown + 费用说明原文
    const modal = await screen.findByRole('dialog', { name: '运行「一键成片」会产生费用' })
    expect(within(modal).getByText(/约 ¥23.40/)).toBeInTheDocument()
    expect(within(modal).getByText(/视频生成 ¥22.50 · 配音 ¥0.90/)).toBeInTheDocument()
    expect(within(modal).getByText('本次预计消耗 ¥23.40。点「取消」不产生任何费用。')).toBeInTheDocument()
    expect(apiMock.post).toHaveBeenCalledTimes(1)

    await user.click(within(modal).getByRole('button', { name: '我知道代价，继续' }))
    expect(apiMock.post).toHaveBeenLastCalledWith(
      '/skills/one-video/run',
      expect.objectContaining({ confirm_cost: true }),
      expect.anything(),
    )
    await waitFor(() => expect(within(drawer).getByRole('button', { name: '运行中…' })).toBeInTheDocument())
  })
})

describe('技能库 · F-C9 密钥配置', () => {
  it('留空不提交；填了值才 POST /api/keys 并刷新运行状态', async () => {
    const { user, dialog } = await openDrawer('一键成片')
    const keyInput = await within(dialog).findByLabelText('MINIMAX_API_KEY')
    await user.click(within(dialog).getByRole('button', { name: '保存密钥' }))
    // value 为空 → 前端就不发（留空不覆盖）
    expect(apiMock.post).not.toHaveBeenCalled()

    await user.type(keyInput, 'sk-test-123')
    apiMock.get.mockImplementation(async (url: string) => {
      if (url === '/skills') return { skills: [FREE, PLANNER, PAID], count: 3, layers: ['策划', '制作'] }
      if (url.startsWith('/skills/runs?')) return { runs: [] }
      if (url === '/skills/one-video')
        return { ...DETAIL_PAID, missing_keys: [], runnable: true, block_reason: null }
      return {}
    })
    await user.click(within(dialog).getByRole('button', { name: '保存密钥' }))
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        '/keys',
        { key_name: 'MINIMAX_API_KEY', value: 'sk-test-123' },
        expect.anything(),
      ),
    )
    // 保存后重拉详情，运行按钮解禁
    await waitFor(() => expect(within(dialog).getByRole('button', { name: '运行' })).toBeEnabled())
  })
})
