/**
 * 发布中心前端测试（SPEC-06 §8 验收项对应的交互）。
 *
 * ★ 刻意**不 mock 字数计数**：字数读数必须原样来自后端
 * （`variant.char_count` / `char_limit`），前端自己再数一遍就是 SPEC-06 §2 的违规。
 * 所以这里断言的是「后端给 61/55，前端就显示 61/55 并标红」。
 */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastHost } from '@/components'
import { PublishPage } from '@/features/publish/PublishPage'
import { PlatformVariantCard } from '@/features/publish/PlatformVariantCard'
import { PrecheckPanel } from '@/features/publish/PrecheckPanel'
import { PublishStatusList } from '@/features/publish/PublishStatusList'
import type { PlatformMeta, PlatformRun, PlatformVariant, PrecheckItem } from '@/features/publish/types'

/* ------------------------------------------------------------------ 数据 */

const DY_OVER: PlatformVariant = {
  platform: 'dy',
  title: '我用 3 个 Agent 把内容流程砍掉一半',
  body: '正文',
  char_count: 61, // ← 后端算好的读数
  char_limit: 55,
  over_limit: true,
  adapted: true,
  status: 'ready',
  error: null,
  published_url: null,
}

const XHS_OK: PlatformVariant = {
  platform: 'xhs',
  title: '小红书标题',
  body: '正文内容',
  char_count: 618,
  char_limit: 1000,
  over_limit: false,
  adapted: true,
  status: 'ready',
  error: null,
  published_url: null,
}

const PLATFORMS: PlatformMeta[] = [
  {
    platform: 'xhs', name: '小红书', forms: ['image', 'video'], form_label: '图文 / 视频',
    title_max: 20, body_max: 1000, needs_cover: true, cover_ratio: '3:4',
    constraint: '图文 / 视频 · 需封面图（3:4）· 正文 ≤ 1000 字',
    auth: { platform: 'xhs', logged_in: true, account: '@ai', need_sms: false, message: '有效', verified_at: null },
  },
  {
    platform: 'dy', name: '抖音', forms: ['video'], form_label: '视频',
    title_max: 55, body_max: 55, needs_cover: false, cover_ratio: null,
    constraint: '视频 · 正文 ≤ 55 字',
    auth: { platform: 'dy', logged_in: true, account: '@ai', need_sms: true, message: '有效', verified_at: null },
  },
  {
    platform: 'gzh', name: '微信公众号', forms: ['image', 'text'], form_label: '图文 / 长文',
    title_max: 64, body_max: 20000, needs_cover: true, cover_ratio: '2.35:1',
    constraint: '图文 / 长文 · 需封面图（2.35:1）',
    auth: { platform: 'gzh', logged_in: false, account: null, need_sms: false, message: '未登录', verified_at: null },
  },
]

const DRAFT = {
  id: 'pd_1', project: null, title: '我用 3 个 Agent 把内容流程砍掉一半',
  body: '母版正文', topic_tags: ['AI工作流'],
  variants: [XHS_OK, DY_OVER], attachments: [],
  topic_id: null, scheduled_date: null,
  created_at: '', updated_at: '',
}

function item(p: Partial<PrecheckItem>): PrecheckItem {
  return { id: 'x', label: 'x', severity: 'warn', passed: true, message: 'm', fix_hint: null, platform: null, ...p }
}

/* ------------------------------------------------------------------ fetch */

let calls: { url: string; method: string; body: unknown }[] = []

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** 预检响应：可按用例覆盖（超字数 → blocked=true） */
let precheckResponse: Record<string, unknown> = {
  items: [
    item({ id: 'compliance', label: '合规风险扫描', severity: 'block', passed: true, message: '极限词 0' }),
    item({ id: 'title_score', label: '标题打分', severity: 'warn', passed: true, message: '钩子 8.5' }),
  ],
  blocked: false,
  block_count: 0,
  warn_count: 0,
}

const BLOCKED_PRECHECK = {
  items: [
    item({ id: 'compliance', label: '合规风险扫描', severity: 'block', passed: true, message: '极限词 0' }),
    item({ id: 'wordcount:dy', label: '抖音标题超字数（硬门禁）', severity: 'block', passed: false, platform: 'dy', message: '61 / 55 字' }),
    item({ id: 'persona', label: '人设一致性（软提醒，不阻断）', severity: 'warn', passed: false, message: '软提醒，不阻断' }),
  ],
  blocked: true,
  block_count: 1,
  warn_count: 1,
}

beforeEach(() => {
  calls = []
  precheckResponse = { items: [], blocked: false, block_count: 0, warn_count: 0 }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push({ url: String(url), method, body: init?.body ? JSON.parse(String(init.body)) : null })
      if (String(url).includes('/publish/platforms')) return json({ platforms: PLATFORMS })
      if (String(url).includes('/api/topics')) {
        return json({ items: [{ id: 'topic-1', title: '关联用选题' }], total: 1 })
      }
      if (String(url).includes('/precheck')) return json(precheckResponse)
      if (String(url).endsWith('/publish/drafts') && method === 'GET') return json({ drafts: [DRAFT] })
      if (String(url).endsWith('/publish/drafts') && method === 'POST') return json(DRAFT)
      if (/\/publish\/drafts\/[^/]+$/.test(String(url)) && method === 'GET') return json(DRAFT)
      if (/\/publish\/drafts\/[^/]+$/.test(String(url)) && method === 'PATCH') {
        return json({ ...DRAFT, ...(init?.body ? JSON.parse(String(init.body)) : {}), updated_at: '2026-10-02T14:41:00Z' })
      }
      if (String(url).includes('/records')) return json({ records: [] })
      return json({})
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function renderPage() {
  // ToastHost 必须一起渲染：App 根部才有它，断言 toast 文本要靠它
  return render(
    <MemoryRouter>
      <>
        <PublishPage />
        <ToastHost />
      </>
    </MemoryRouter>,
  )
}

describe('发布中心 · 排期与关联选题（SPEC-10 §3）', () => {
  it('改计划发布日 / 关联选题 → 立即触发 PATCH 且带对应字段', async () => {
    renderPage()
    const dateInput = await screen.findByLabelText('计划发布日')
    fireEvent.change(dateInput, { target: { value: '2026-11-01' } })
    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.method === 'PATCH' && (c.body as Record<string, unknown>)?.scheduled_date === '2026-11-01',
        ),
      ).toBe(true),
    )
    // 关联选题下拉（候选项来自 /topics）
    const select = screen.getByLabelText('关联选题')
    await waitFor(() => expect((select as HTMLSelectElement).options.length).toBeGreaterThan(1))
    fireEvent.change(select, { target: { value: 'topic-1' } })
    await waitFor(() =>
      expect(
        calls.some((c) => c.method === 'PATCH' && (c.body as Record<string, unknown>)?.topic_id === 'topic-1'),
      ).toBe(true),
    )
  })

  it('排期后清空 → PATCH scheduled_date 为 null', async () => {
    renderPage()
    const dateInput = await screen.findByLabelText('计划发布日')
    fireEvent.change(dateInput, { target: { value: '2026-11-01' } })
    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.method === 'PATCH' && (c.body as Record<string, unknown>)?.scheduled_date === '2026-11-01',
        ),
      ).toBe(true),
    )
    fireEvent.change(dateInput, { target: { value: '' } })
    await waitFor(() =>
      expect(
        calls.some((c) => c.method === 'PATCH' && (c.body as Record<string, unknown>)?.scheduled_date === null),
      ).toBe(true),
    )
  })
})

/* ------------------------------------------------------------------ 用例 */

describe('发布中心 · 平台字数与超限标红（UI-SPEC 规则 16）', () => {
  it('逐平台显示后端给的读数；抖音 61/55 标红，小红书 618/1000 正常', async () => {
    render(
      <PlatformVariantCard variant={DY_OVER} />,
    )
    const dy = screen.getByTestId('cnt-dy')
    expect(dy).toHaveTextContent('61 / 55')
    expect(dy.className).toContain('over')
    expect(screen.getByTestId('pv-dy')).toHaveAttribute('data-over', 'true')
    expect(screen.getByText(/超出上限 6 字/)).toBeInTheDocument()

    render(<PlatformVariantCard variant={XHS_OK} />)
    const xhs = screen.getByTestId('cnt-xhs')
    expect(xhs).toHaveTextContent('618 / 1000')
    expect(xhs.className).not.toContain('over')
  })

  it('适配中逐字渲染（打字机光标）', () => {
    render(<PlatformVariantCard variant={{ ...DY_OVER, status: 'adapting' }} streaming="正在写…" />)
    expect(screen.getByTestId('pv-body-dy')).toHaveTextContent('正在写…')
    expect(screen.getByLabelText('适配中')).toBeInTheDocument()
  })
})

describe('发布中心 · 预检分硬门禁与软提醒（UI-SPEC 规则 17）', () => {
  const result = {
    items: [
      item({ id: 'compliance', label: '合规风险扫描', severity: 'block', passed: true, message: '极限词 0' }),
      item({ id: 'wordcount:dy', label: '抖音标题超字数（硬门禁）', severity: 'block', passed: false, platform: 'dy', message: '61 / 55 字', fix_hint: '点「一键裁剪」' }),
      item({ id: 'persona', label: '人设一致性（软提醒，不阻断）', severity: 'warn', passed: false, message: '出现黑话（软提醒，不阻断）' }),
      item({ id: 'title_score', label: '标题打分', severity: 'warn', passed: true, message: '钩子 8.5' }),
    ],
    blocked: true,
    block_count: 1,
    warn_count: 1,
  }

  it('红 ✗ 硬门禁带「一键裁剪」；琥珀 ! 人设项不带阻断按钮', async () => {
    const onAutofix = vi.fn()
    render(<PrecheckPanel result={result} loading={false} onAutofix={onAutofix} onGoAccounts={vi.fn()} onGoLibrary={vi.fn()} onRerun={vi.fn()} />)

    expect(screen.getByTestId('precheck-wordcount:dy')).toHaveAttribute('data-tone', 'd')
    expect(screen.getByTestId('precheck-persona')).toHaveAttribute('data-tone', 'w') // 人设=琥珀，只告警
    expect(document.querySelector('.precheck-blocks')).toHaveTextContent('1 项待处理')

    await userEvent.click(screen.getByTestId('autofix-dy'))
    expect(onAutofix).toHaveBeenCalledWith('dy', 'title')
  })

  it('抖音标题与正文都超限时，「一键裁剪」两个都裁（否则门禁解不掉）', async () => {
    const onAutofix = vi.fn()
    render(
      <PrecheckPanel
        result={{
          items: [
            item({
              id: 'wordcount:dy', label: '抖音标题超字数（硬门禁）', severity: 'block',
              passed: false, platform: 'dy', message: '标题 61 / 55 字，正文 66 / 55 字',
            }),
          ],
          blocked: true, block_count: 1, warn_count: 0,
        }}
        loading={false}
        onAutofix={onAutofix}
        onGoAccounts={vi.fn()}
        onGoLibrary={vi.fn()}
        onRerun={vi.fn()}
      />,
    )
    await userEvent.click(screen.getByTestId('autofix-dy'))
    expect(onAutofix).toHaveBeenCalledWith('dy', 'all')
  })

  it('★ 人设不一致时预检不阻断（只有 WARN）→ 可以发布', async () => {
    render(
      <PrecheckPanel
        result={{ ...result, blocked: false, block_count: 0, warn_count: 2 }}
        loading={false}
        onAutofix={vi.fn()}
        onGoAccounts={vi.fn()}
        onGoLibrary={vi.fn()}
        onRerun={vi.fn()}
      />,
    )
    expect(document.querySelector('.precheck-blocks')).toBeNull()
    expect(screen.getByTestId('precheck-persona')).toHaveAttribute('data-tone', 'w')
    // 文案明确告诉用户「人设不一致不拦发布」（文案里 <b>会</b> 把句子拆开，用函数匹配器）
    expect(
      screen.getByText((_, el) => el?.tagName === 'P' && (el.textContent ?? '').includes('不会拦你发布')),
    ).toBeInTheDocument()
  })
})

describe('发布中心 · 失败给明确原因 + 错误码（原则四 / UI-SPEC 规则 21）', () => {
  it('单平台失败显示原因 + 错误码 + [去登录]；另一个平台仍显示已发', () => {
    const runs: PlatformRun[] = [
      {
        platform: 'dy', name: '抖音', status: 'failed', url: null,
        error: '抖音发布失败：登录态已过期，需重新扫码',
        error_code: 'dy_auth_4012',
        hint: '登录态过期，需重新扫码 + 短信验证码',
        record_id: 'rec_1', dry_run: true, raw: {},
      },
      {
        platform: 'xhs', name: '小红书', status: 'sent', url: null,
        error: null, error_code: null, hint: null, record_id: 'rec_2', dry_run: true, raw: {},
      },
    ]
    render(<PublishStatusList runs={runs} records={[]} pendingPlatforms={[]} onGoAccounts={vi.fn()} onRetry={vi.fn()} />)

    const dy = screen.getByTestId('run-dy')
    expect(within(dy).getByText(/登录态已过期，需重新扫码/)).toBeInTheDocument()
    expect(within(dy).getByText(/错误码 dy_auth_4012/)).toBeInTheDocument()
    expect(within(dy).getByRole('button', { name: '去登录' })).toBeInTheDocument()

    expect(screen.getByTestId('run-xhs')).toHaveAttribute('data-status', 'sent')
    // dry-run 诚实标注：不能让人以为真发出去了
    expect(within(screen.getByTestId('run-xhs')).getByText('模拟')).toBeInTheDocument()
  })
})

describe('发布中心 · 页面关键交互', () => {
  it('勾选平台 → 顶栏按钮文案变「发布到 N 个平台」', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('平台适配')).toBeInTheDocument())
    const btn = () => screen.getByRole('button', { name: /发布到 \d+ 个平台/ })
    await waitFor(() => expect(btn()).toHaveTextContent('发布到 2 个平台'))
    await userEvent.click(screen.getByRole('button', { name: /微信公众号（未选择）/ }))
    await waitFor(() => expect(btn()).toHaveTextContent('发布到 3 个平台'))
  })

  it('★ 抖音超字数时点发布 → toast「硬门禁未解除」且不发请求', async () => {
    // 抖音 61/55 → 后端预检 blocked=true
    precheckResponse = BLOCKED_PRECHECK
    renderPage()
    await waitFor(() => expect(screen.getByText('平台适配')).toBeInTheDocument())
    const publishBtn = screen.getByRole('button', { name: /发布到 \d+ 个平台/ })
    await waitFor(() => expect(publishBtn).toBeEnabled())

    await userEvent.click(publishBtn)

    // 预检返回 blocked → toast 警示，且绝不调 publish 端点
    await waitFor(() => {
      const toastText = document.querySelector('[data-testid="toasts"]')?.textContent ?? ''
      expect(toastText).toContain('硬门禁未解除')
    })
    expect(screen.queryByText('确认发布')).not.toBeInTheDocument()
    expect(calls.some((c) => c.url.endsWith('/publish'))).toBe(false)
    // 预检确实跑过了（证明是真的被门禁拦下，不是压根没触发）
    expect(calls.some((c) => c.url.includes('/precheck'))).toBe(true)
  })

  it('★ 草稿改动 debounce 800ms 后自动保存，显示「草稿自动保存 · HH:MM」', async () => {
    const errSpy = vi.spyOn(console, 'error')
    renderPage()
    await waitFor(() => expect((screen.getByLabelText('标题') as HTMLInputElement).value).toBeTruthy())
    const before = calls.filter((c) => c.method === 'PATCH').length

    await userEvent.type(screen.getByLabelText('标题'), '加字')
    // debounce 未到，不该已经发请求
    expect(calls.filter((c) => c.method === 'PATCH').length).toBe(before)

    await waitFor(() => expect(calls.filter((c) => c.method === 'PATCH').length).toBe(before + 1), {
      timeout: 2000,
    })
    // 显示「草稿自动保存 · HH:MM」（钟点按本机时区渲染，这里只断言形状）
    await waitFor(() =>
      expect(screen.getByTestId('autosave-hint')).toHaveTextContent(/^草稿自动保存 · \d{2}:\d{2}$/),
    )
    // publish 页不许有 console 错误（验收第 9 条）
    expect(errSpy).not.toHaveBeenCalled()
  })
})
