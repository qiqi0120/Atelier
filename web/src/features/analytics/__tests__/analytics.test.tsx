/** SPEC-11 §6 · 数据复盘页前端测试（M2-3a）+ M5 数据录入区。
 *
 * 覆盖：四工具卡渲染 · 诊断诚实空态（记录不足）· 诊断结果状态色与 notice ·
 * 竞品三列表与存入选题库请求体 · 策略 markdown 渲染 · 门禁 BLOCK 改法展示 ·
 * 录入三卡渲染 · 快照/表现/台账弹层请求体 · records-recent 下拉 · insufficient/422 展示。
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

import { AnalyticsPage } from '../AnalyticsPage'
import type { DiagnoseResponse } from '../types'

const STATS = {
  records_total: 6,
  records_last_30d: 5,
  records_failed: 0,
  by_platform: { dy: 5, xhs: 1 },
  drafts_total: 2,
  topics_flow: { todo: 3, doing: 1, done: 2 },
  recent_titles: ['标题甲'],
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/analytics']}>
      <AnalyticsPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  apiMock.get.mockReset()
  apiMock.post.mockReset()
  apiMock.patch.mockReset()
  apiMock.del.mockReset()
  // 页面挂载即拉录入区小字（快照最近一条 + ROI 汇总）；各用例可覆盖
  apiMock.get.mockImplementation(async (url: string) => {
    if (url.startsWith('/attribution/snapshots')) return { items: [], total: 0 }
    if (url.startsWith('/attribution/roi/summary'))
      return { insufficient: true, need: 1, message: '近 30 天还没有投入记录' }
    if (url.startsWith('/attribution/records-recent')) return { items: [], total: 0 }
    return {}
  })
})

describe('数据复盘 · 工具卡装配', () => {
  it('渲染三张工具卡与账号诊断主行动', () => {
    renderPage()
    expect(screen.getByTestId('insights-grid')).toBeInTheDocument()
    for (const title of ['内容策略', '受众画像卡', '竞品分析']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: '账号诊断' })).toBeInTheDocument()
  })
})

describe('数据复盘 · 账号诊断（F-E13 诚实模式）', () => {
  it('记录不足：显示数据不足空态，不显示任何 findings', async () => {
    const user = userEvent.setup()
    apiMock.post.mockResolvedValueOnce({
      insufficient: true,
      stats: { ...STATS, records_total: 2 },
      need: 5,
      message: '发布满 5 条后才有诊断（当前 2 条）——不编造分数',
    })
    renderPage()
    await user.click(screen.getByRole('button', { name: '账号诊断' }))
    await user.click(screen.getByRole('button', { name: '开始诊断' }))
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(dialog).toHaveTextContent(/发布满 5 条后才有诊断/))
    expect(dialog).toHaveTextContent(/不编造分数/)
    // 只调了诊断接口
    expect(apiMock.post).toHaveBeenCalledWith(
      '/analytics/diagnose',
      expect.objectContaining({ profile_id: expect.anything() }),
      expect.anything(),
    )
  })

  it('正常诊断：findings 按状态上色，notice 标注 M5 依赖', async () => {
    const user = userEvent.setup()
    const result: DiagnoseResponse = {
      insufficient: false,
      stats: STATS,
      findings: [
        { dimension: '垂直度', status: 'good', note: '5 条记录里 4 条抖音' },
        { dimension: '更新节奏', status: 'bad', note: '近 30 天仅 5 条' },
      ],
      advice: ['把周更固定到周三'],
      notice: '限流信号与流量池阶段需要平台侧数据回收（M5），当前诊断仅基于本地记录。',
      gate_report: { blocked: false, items: [], summary: { total: 0, failed: 0, blocked_items: 0, warn_items: 0 } },
    }
    apiMock.post.mockResolvedValueOnce(result)
    renderPage()
    await user.click(screen.getByRole('button', { name: '账号诊断' }))
    await user.click(screen.getByRole('button', { name: '开始诊断' }))
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(dialog).toHaveTextContent(/限流信号与流量池阶段/))
    expect(dialog).toHaveTextContent('垂直度 — 5 条记录里 4 条抖音')
    expect(dialog).toHaveTextContent('更新节奏 — 近 30 天仅 5 条')
    expect(dialog).toHaveTextContent('把周更固定到周三')
  })
})

describe('数据复盘 · 竞品分析（F-D10）', () => {
  it('三列表渲染；选题存入走 POST /topics 且带 source_ref=竞品分析', async () => {
    const user = userEvent.setup()
    apiMock.post.mockImplementation(async (url: string) => {
      if (url === '/analytics/competitor') {
        return {
          topics: ['平价通勤穿搭公式'],
          formats: ['三图一文'],
          patterns: ['首图信息密度高'],
          gate_report: { blocked: false, items: [], summary: { total: 0, failed: 0, blocked_items: 0, warn_items: 0 } },
        }
      }
      return { id: 'topic-new' }
    })
    renderPage()
    await user.click(screen.getByRole('button', { name: '生成：竞品分析' }))
    const dialog = await screen.findByRole('dialog')
    const input = within(dialog).getByLabelText(/竞品原文/)
    await user.type(input, '这是一段足够长的竞品内容，用来通过四十字的最低门槛，多写一点凑够字数再开始分析。')
    await user.click(within(dialog).getByRole('button', { name: '开始分析' }))
    await waitFor(() => expect(dialog).toHaveTextContent('平价通勤穿搭公式'))
    expect(dialog).toHaveTextContent('TA 用的格式')
    expect(dialog).toHaveTextContent('首图信息密度高')
    await user.click(within(dialog).getByRole('button', { name: '存入选题库' }))
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        '/topics',
        expect.objectContaining({ title: '平价通勤穿搭公式', source: 'manual', source_ref: '竞品分析' }),
        expect.anything(),
      ),
    )
  })
})

describe('数据复盘 · 内容策略（F-E12）', () => {
  it('markdown 渲染四段策略', async () => {
    const user = userEvent.setup()
    apiMock.post.mockResolvedValueOnce({
      markdown: '## 内容支柱架构\n评测 40%。\n\n## 受众路径\n刷到 → 关注。\n\n## 90 天节奏\n按月三阶段。\n\n## KPI\n涨粉 1000。',
      sections: { 内容支柱: true, 受众路径: true, '90 天': true, KPI: true },
      gate_report: { blocked: false, items: [], summary: { total: 0, failed: 0, blocked_items: 0, warn_items: 0 } },
    })
    renderPage()
    await user.click(screen.getByRole('button', { name: '生成：内容策略' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: '生成策略' }))
    await waitFor(() => expect(within(dialog).getByRole('heading', { name: '内容支柱架构' })).toBeInTheDocument())
    expect(dialog).toHaveTextContent('涨粉 1000。')
  })
})

describe('数据复盘 · 门禁 BLOCK（PRD 原则二）', () => {
  it('BLOCK 弹层内逐项展示改法', async () => {
    const user = userEvent.setup()
    apiMock.post.mockRejectedValueOnce(
      new ApiErrorMock(
        'GateBlocked', 422, '内容策略未通过硬门禁：极限词',
        {
          gate_items: [
            { gate: 'compliance', label: '合规风险扫描', severity: 'block', passed: false,
              actual: '全网最好', limit: null, message: '出现极限词「全网最好」', fix_hint: '改成「少见的」这类可验证表述' },
          ],
          summary: { total: 3, failed: 1, blocked_items: 1, warn_items: 0 },
        },
        '先按改法修改后再试',
      ),
    )
    renderPage()
    await user.click(screen.getByRole('button', { name: '生成：内容策略' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: '生成策略' }))
    await waitFor(() => expect(within(dialog).getByRole('alert')).toBeInTheDocument())
    expect(within(dialog).getByRole('alert')).toHaveTextContent('改法：改成「少见的」这类可验证表述')
  })
})

describe('数据复盘 · 策划域 P3（SPEC-12 §3）', () => {
  it('渲染三张策划卡', () => {
    renderPage()
    const grid = screen.getByTestId('plan-grid')
    for (const title of ['营销活动策划', '直播策划', '商单方案']) {
      expect(within(grid).getByText(title)).toBeInTheDocument()
    }
  })

  it('营销策划弹层发请求体（theme + occasion）', async () => {
    const user = userEvent.setup()
    apiMock.post.mockResolvedValueOnce({
      markdown: '## 活动目标\n\nx',
      sections: {},
      gate_report: { blocked: false, items: [], failed: 0, warnings: 0 },
    })
    renderPage()
    await user.click(screen.getByRole('button', { name: '策划：营销活动策划' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('活动主题 *'), '双11 好物节')
    await user.type(within(dialog).getByLabelText('场景（可选）'), '电商大促')
    await user.click(within(dialog).getByRole('button', { name: '生成方案' }))
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        '/analytics/campaign',
        expect.objectContaining({ theme: '双11 好物节', occasion: '电商大促' }),
        expect.anything(),
      ),
    )
  })

  it('缺段 422：弹层内展示改法（不硬编补段）', async () => {
    const user = userEvent.setup()
    apiMock.post.mockRejectedValueOnce(
      new ApiErrorMock(
        'InsightsIncomplete',
        422,
        '营销方案缺段：渠道分工、预算与KPI',
        { missing: ['渠道分工', '预算与KPI'] },
        '重试一次；连续失败就把任务拆小或换模型',
      ),
    )
    renderPage()
    await user.click(screen.getByRole('button', { name: '策划：营销活动策划' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('活动主题 *'), '新年企划')
    await user.click(within(dialog).getByRole('button', { name: '生成方案' }))
    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent('缺段')
    expect(alert).toHaveTextContent('重试一次')  // hint 一并展示（describeError 格式）
  })
})

describe('数据录入 · M5 录入区（SPEC-15）', () => {
  it('渲染三张录入卡；M5 占位 EmptyState 已换成真实说明', () => {
    renderPage()
    const grid = screen.getByTestId('entry-grid')
    for (const title of ['账号快照', '内容表现', '投入台账']) {
      expect(within(grid).getByText(title)).toBeInTheDocument()
    }
    expect(screen.getByText(/平台不提供公开数据接口/)).toBeInTheDocument()
    expect(screen.queryByText(/属 M5/)).not.toBeInTheDocument()
  })

  it('快照卡小字显示最近一条；弹层录入请求体正确并在成功后刷新', async () => {
    const user = userEvent.setup()
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/attribution/snapshots'))
        return {
          items: [
            {
              id: 'snap-1', platform: 'xhs', captured_at: '2026-09-25',
              followers: 1200, likes_total: 8000, works_total: 30,
              note: '', created_at: '', updated_at: '',
            },
          ],
          total: 1,
        }
      if (url.startsWith('/attribution/roi/summary')) return { insufficient: true }
      return {}
    })
    apiMock.post.mockResolvedValueOnce({ id: 'snap-2' })
    renderPage()
    expect(await screen.findByText(/最近一条：2026-09-25 · xhs · 粉丝 1200/)).toBeInTheDocument()
    const getSnapshotsCalls = () =>
      apiMock.get.mock.calls.filter((c) => String(c[0]).startsWith('/attribution/snapshots')).length

    await user.click(screen.getByRole('button', { name: '录入：账号快照' }))
    const dialog = await screen.findByRole('dialog')
    await user.selectOptions(within(dialog).getByLabelText('平台'), 'xhs')
    // 默认日期已填今天（YYYY-MM-DD），只改粉丝数
    await user.type(within(dialog).getByLabelText('粉丝数'), '1300')
    const before = getSnapshotsCalls()
    await user.click(within(dialog).getByRole('button', { name: '录入快照' }))
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        '/attribution/snapshots',
        expect.objectContaining({
          platform: 'xhs',
          followers: 1300, // 输入框初始 '0'，追加输入后 '01300' → Number 1300
          captured_at: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
        }),
        expect.anything(),
      ),
    )
    // 成功后触发卡内小字刷新（onSaved → 重新 GET snapshots）
    await waitFor(() => expect(getSnapshotsCalls()).toBeGreaterThan(before))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('快照缺平台：客户端校验，弹层内 role="alert"，不发请求', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByRole('button', { name: '录入：账号快照' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: '录入快照' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('先选平台')
    expect(apiMock.post).not.toHaveBeenCalled()
  })

  it('表现弹层的记录下拉来自 records-recent，提交带 record_id 与自动平台', async () => {
    const user = userEvent.setup()
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/attribution/records-recent'))
        return {
          items: [
            { id: 'pr-1', platform: 'dy', title: '三条视频结构', created_at: '2026-09-24T10:00:00+00:00', draft_title: '' },
            { id: 'pr-2', platform: 'xhs', title: '', created_at: '2026-09-20T10:00:00+00:00', draft_title: '图文草稿' },
          ],
          total: 2,
        }
      return {}
    })
    apiMock.post.mockResolvedValueOnce({ id: 'met-1' })
    renderPage()
    await user.click(screen.getByRole('button', { name: '录入：内容表现' }))
    const dialog = await screen.findByRole('dialog')
    const sel = within(dialog).getByLabelText('发布记录') as HTMLSelectElement
    await waitFor(() => expect(within(sel).getAllByRole('option')).toHaveLength(3)) // placeholder + 2 条
    // 选项格式「平台 · 标题 · 时间」；无标题回退草稿标题
    expect(within(sel).getByRole('option', { name: 'dy · 三条视频结构 · 2026-09-24' })).toBeInTheDocument()
    expect(within(sel).getByRole('option', { name: 'xhs · 图文草稿 · 2026-09-20' })).toBeInTheDocument()
    await user.selectOptions(sel, 'pr-1')
    // 平台自动带出且只读
    expect(within(dialog).getByLabelText('平台（随所选记录）')).toHaveValue('dy')
    await user.type(within(dialog).getByLabelText('播放'), '5000')
    await user.click(within(dialog).getByRole('button', { name: '录入表现' }))
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        '/attribution/metrics',
        expect.objectContaining({ record_id: 'pr-1', platform: 'dy', views: 5000 }),
        expect.anything(),
      ),
    )
  })

  it('表现没记录可选拉：提交按钮禁用并说明原因，不发请求', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByRole('button', { name: '录入：内容表现' }))
    const dialog = await screen.findByRole('dialog')
    const sel = await within(dialog).findByLabelText('发布记录')
    await waitFor(() => expect((sel as HTMLSelectElement).options.length).toBeGreaterThan(0))
    const submit = within(dialog).getByRole('button', { name: '录入表现' })
    expect(submit).toBeDisabled()
    // 禁用原因挂在包装元素上（UI-SPEC §4：禁用必须说明原因）
    expect(submit.closest('.btn-wrap')).toHaveAttribute(
      'aria-label',
      '禁用原因：还没有发布记录，先去发布一条（dry-run 也算）',
    )
    await user.click(submit)
    expect(apiMock.post).not.toHaveBeenCalled()
  })

  it('台账卡 insufficient 小字；422 错误在弹层内展示 message + hint', async () => {
    const user = userEvent.setup()
    renderPage()
    expect(await screen.findByText('还没有投入记录')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '录入：投入台账' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('投入小时数'), '-1')
    await user.type(within(dialog).getByLabelText('投入金额（元）'), '5')
    apiMock.post.mockRejectedValueOnce(
      new ApiErrorMock('ValidationError', 422, 'hours 不能为负数', { field: 'hours' }, '计数没有负数；想清零就填 0'),
    )
    await user.click(within(dialog).getByRole('button', { name: '记一笔' }))
    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent('hours 不能为负数')
    expect(alert).toHaveTextContent('想清零就填 0')
  })

  it('台账成功后 toast 由父级刷新合计小字（total_hours / total_amount）', async () => {
    const user = userEvent.setup()
    let roiBody: Record<string, unknown> = { insufficient: true, need: 1 }
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/attribution/roi/summary')) return roiBody
      return {}
    })
    apiMock.post.mockImplementation(async () => {
      roiBody = { insufficient: false, days: 30, total_hours: 2.5, total_amount: 40 }
      return { id: 'roi-1' }
    })
    renderPage()
    expect(await screen.findByText('还没有投入记录')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '录入：投入台账' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('投入小时数'), '2.5')
    await user.type(within(dialog).getByLabelText('投入金额（元）'), '40')
    await user.click(within(dialog).getByRole('button', { name: '记一笔' }))
    expect(await screen.findByText('近 30 天：2.5 小时 / 40 元')).toBeInTheDocument()
    expect(apiMock.post).toHaveBeenCalledWith(
      '/attribution/roi',
      expect.objectContaining({ hours: 2.5, amount: 40 }),
      expect.anything(),
    )
  })

  it('台账双零：客户端校验拦下，不发请求', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByRole('button', { name: '录入：投入台账' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: '记一笔' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('至少一项大于 0')
    expect(apiMock.post).not.toHaveBeenCalled()
  })
})
