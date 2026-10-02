/** SPEC-08 §6/§8 · 选题库前端测试（M2-1）。
 *
 * 覆盖四条用户链路 + 看板装配：
 * 1. 看板三列与选题卡
 * 2. 新建选题（F-E1/E2 最小可用）
 * 3. 爆款拆解 → 存入选题库（F-E8）
 * 4. 评分展示 7 维与确定性结论（F-E9）
 * 5. 钩子逐条字数判定 + 设为标题（F-E11）
 * 6. 删除二次确认
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { ApiError } from '@/lib/api'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { apiMock, ApiErrorMock } = vi.hoisted(() => {
  /** 与真实 ApiError 同形的替身：describe.ts 里 instanceof 按 mock 的类判 */
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

import { TopicsPage } from '../TopicsPage'
import type { Topic, TopicsResponse } from '../types'

function topic(over: Partial<Topic> = {}): Topic {
  return {
    id: 'topic-a',
    profile_id: null,
    title: '3 套通勤公式，小个子直接抄',
    angle: '按身高给参数',
    source: 'matrix',
    source_ref: '通勤穿搭×图文',
    status: 'todo',
    decode: '',
    created_at: '2026-10-02T10:00:00+00:00',
    updated_at: '2026-10-02T10:00:00+00:00',
    ...over,
  }
}

const POOL: TopicsResponse = {
  items: [
    topic(),
    topic({ id: 'topic-b', title: '跟拍通勤出门流程', status: 'doing', source: 'manual' }),
    topic({ id: 'topic-c', title: '已发布的复盘选题', status: 'done', source: 'decode' }),
  ],
  total: 3,
}

beforeEach(() => {
  // mockReset（而不是 clearAllMocks）：把上一条测试没消费掉的 Once 队列也清掉，
  // 否则一条失败会污染后面的测试，失败原因面目全非。
  apiMock.get.mockReset()
  apiMock.post.mockReset()
  apiMock.patch.mockReset()
  apiMock.del.mockReset()
  apiMock.get.mockImplementation((url: string) => {
    if (url.startsWith('/topics/')) {
      const t = POOL.items[0]
      return Promise.resolve({ topic: t, score: null })
    }
    if (url.startsWith('/topics')) return Promise.resolve(POOL)
    return Promise.resolve({})
  })
  apiMock.post.mockResolvedValue({})
  apiMock.patch.mockResolvedValue({})
  apiMock.del.mockResolvedValue({ ok: true, id: 'topic-a' })
})

const page = () =>
  render(
    <MemoryRouter>
      <TopicsPage />
    </MemoryRouter>,
  )

describe('看板装配', () => {
  it('三列看板：待做/进行中/已完成 + 各列计数与来源 chip', async () => {
    page()
    await waitFor(() => expect(screen.getByTestId('topics-board')).toBeInTheDocument())
    for (const label of ['待做', '进行中', '已完成']) {
      expect(screen.getByRole('heading', { name: label })).toBeInTheDocument()
    }
    expect(screen.getByTestId('col-todo').textContent).toContain('3 套通勤公式')
    expect(screen.getByTestId('col-doing').textContent).toContain('跟拍通勤出门流程')
    expect(screen.getByTestId('col-done').textContent).toContain('已发布的复盘选题')
  })

  it('空池给下一步动作（打开爆款拆解）', async () => {
    apiMock.get.mockResolvedValue({ items: [], total: 0 })
    page()
    const btn = await screen.findByRole('button', { name: '先拆一条爆款试试' })
    expect(btn).toBeInTheDocument()
  })
})

describe('新建选题（F-E1/E2 最小可用）', () => {
  it('填标题创建，POST /topics 带上角度', async () => {
    const user = userEvent.setup()
    apiMock.post.mockResolvedValue(topic({ id: 'topic-new', title: '新选题' }))
    page()
    await user.click(await screen.findByRole('button', { name: '新建选题' }))
    await user.type(screen.getByLabelText(/标题/), '新选题标题')
    await user.type(screen.getByLabelText(/备注角度/), '先试一版')
    await user.click(screen.getByRole('button', { name: '创建' }))
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledTimes(1))
    const [url, body] = apiMock.post.mock.calls[0]
    expect(url).toBe('/topics')
    expect(body).toMatchObject({ title: '新选题标题', angle: '先试一版' })
  })
})

describe('爆款拆解（F-E8）', () => {
  /** ≥40 字的合格原文。**千万别改短**：按钮会因后端同口径的最小长度校验禁用，
   * post 不发出，Once 队列污染后面的用例（mockReset 已兜底，但别再踩）。 */
  const LONG_TEXT =
    '这篇笔记讲了打工人的三套通勤穿搭公式，开头直接抛结论不铺垫，评论区都在要链接，' +
    '数据表现是赞 3.2w 藏 1.1w 评 876，非常适合做拆解模板。'

  const DECODE = {
    decode_markdown: '## 概括\n一篇笔记\n\n## 钩子\n开头很强\n\n## 结构\n反常识 → 证据\n\n## 为何火\n选题高频\n\n## 可复制模板\n当 ⟨场景⟩ 时\n\n## 结合画像出选题\n- 选题A',
    sections: { 概括: true, 钩子: true, 结构: true, 为何火: true, 可复制模板: true, 结合画像出选题: true },
    gate_report: { blocked: false, items: [], summary: { total: 0, failed: 0, blocked_items: 0, warn_items: 0 } },
    topic_seed: { title: '对标原文首行', angle: '' },
  }

  it('拆解结果渲染 markdown，一键保存带 source=decode 与拆解正文', async () => {
    const user = userEvent.setup()
    page()
    await user.click(await screen.findByRole('button', { name: '爆款拆解' }))
    await user.type(screen.getByLabelText(/对标原文/), LONG_TEXT)
    apiMock.post.mockResolvedValueOnce(DECODE)
    await user.click(screen.getByRole('button', { name: '开始拆解' }))
    expect(await screen.findByTestId('decode-md')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '概括' })).toBeInTheDocument()

    apiMock.post.mockResolvedValueOnce(topic())
    await user.click(screen.getByRole('button', { name: '存入选题库' }))
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledTimes(2))
    const [, body] = apiMock.post.mock.calls[1]
    expect(body).toMatchObject({
      title: '对标原文首行',
      source: 'decode',
      source_ref: '对标原文首行',
      decode: DECODE.decode_markdown,
    })
  })

  it('原文不足 40 字时按钮禁用（后端同口径校验）', async () => {
    const user = userEvent.setup()
    page()
    await user.click(await screen.findByRole('button', { name: '爆款拆解' }))
    await user.type(screen.getByLabelText(/对标原文/), '太短了')
    expect(screen.getByRole('button', { name: '开始拆解' })).toBeDisabled()
  })

  it('门禁 BLOCK 的改法逐项显示在弹层里，不靠 toast', async () => {
    const user = userEvent.setup()
    page()
    await user.click(await screen.findByRole('button', { name: '爆款拆解' }))
    await user.type(screen.getByLabelText(/对标原文/), LONG_TEXT)
    apiMock.post.mockRejectedValueOnce(
      new ApiError('GateBlocked', 422, '拆解结果未通过硬门禁', {
        gate_items: [
          { gate: 'compliance', label: '极限用语', severity: 'block', passed: false, actual: '全网最好', limit: null, message: '命中极限用语：全网最好', fix_hint: '换成可验证的具体说法' },
        ],
      }),
    )
    await user.click(screen.getByRole('button', { name: '开始拆解' }))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('命中极限用语')
    expect(alert.textContent).toContain('换成可验证的具体说法')
  })
})

describe('选题评分（F-E9）', () => {
  const SCORE = {
    id: 's1',
    topic_id: 'topic-a',
    title: '3 套通勤公式',
    dims: { traffic: 4, match: 4, differentiation: 4, timing: 4, monetization: 4, cost: 4, risk: 4 },
    total: 28,
    verdict: 'do' as const,
    reason: '流量与匹配都高',
    created_at: '2026-10-02T10:00:00+00:00',
  }

  it('展示 7 维条、总分与「建议做」结论', async () => {
    const user = userEvent.setup()
    page()
    await waitFor(() => expect(screen.getByTestId('topics-board')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: '评分：3 套通勤公式，小个子直接抄' }))
    apiMock.post.mockResolvedValueOnce(SCORE)
    await user.click(await screen.findByRole('button', { name: '开始评分' }))
    expect(await screen.findByTestId('score-total')).toHaveTextContent('总分 28/35')
    expect(screen.getByText('建议做')).toBeInTheDocument()
    for (const label of ['流量潜力', '账号匹配', '竞争差异化', '时效', '变现', '成本', '风险']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })
})

describe('标题钩子（F-E11）', () => {
  const HOOKS = {
    variants: [
      { text: '打工人的通勤公式', chars: 8, limit: 55, passed: true },
      { text: '这条特别长'.repeat(12), chars: 60, limit: 55, passed: false },
    ],
    gate_report: { blocked: false, items: [], summary: { total: 0, failed: 0, blocked_items: 0, warn_items: 0 } },
  }

  it('逐条显示字数与超限判定，设为标题走 PATCH', async () => {
    const user = userEvent.setup()
    page()
    await waitFor(() => expect(screen.getByTestId('topics-board')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: '钩子：3 套通勤公式，小个子直接抄' }))
    apiMock.post.mockResolvedValueOnce(HOOKS)
    await user.click(await screen.findByRole('button', { name: '生成变体' }))
    const list = await screen.findByTestId('hook-list')
    expect(list.textContent).toContain('8/55')
    expect(list.textContent).toContain('60/55')
    expect(screen.getByText('超限')).toBeInTheDocument()
    expect(screen.getByText('通过')).toBeInTheDocument()

    apiMock.patch.mockResolvedValueOnce(topic())
    await user.click(screen.getByLabelText('设为标题：打工人的通勤公式'))
    await waitFor(() => expect(apiMock.patch).toHaveBeenCalledTimes(1))
    const [url, body] = apiMock.patch.mock.calls[0]
    expect(url).toBe('/topics/topic-a')
    expect(body).toMatchObject({ title: '打工人的通勤公式' })
  })
})

describe('删除保护（UI-SPEC 规则：破坏性操作二次确认）', () => {
  it('走确认弹层，确认后 DELETE', async () => {
    const user = userEvent.setup()
    page()
    await waitFor(() => expect(screen.getByTestId('topics-board')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: '删除：3 套通勤公式，小个子直接抄' }))
    expect(await screen.findByText('删除这条选题？')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '删除选题' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '删除选题' }))
    await waitFor(() => expect(apiMock.del).toHaveBeenCalledTimes(1))
    expect(apiMock.del.mock.calls[0][0]).toBe('/topics/topic-a')
  })
})
