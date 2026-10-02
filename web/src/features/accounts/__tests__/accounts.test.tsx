/** SPEC-14 §4 · 账号登录中心前端测试（accounts 页转正）。
 *
 * 覆盖：7 平台卡渲染 + 登录态三色标 · 录入凭证弹层请求体 · 留空 unchanged 提示 ·
 * 登出确认弹窗（文案含后果）· F-G28 visibilitychange 聚焦刷新。
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastHost } from '@/components'

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

import { AccountsPage } from '../AccountsPage'
import type { AccountItem, AccountsResponse } from '../types'

/* ------------------------------------------------------------------ 数据 */

function item(p: Partial<AccountItem>): AccountItem {
  return {
    platform: 'xhs',
    display_name: '小红书',
    forms: ['image', 'video'],
    title_max: 20,
    body_max: 1000,
    has_credential: false,
    auth: {
      platform: 'xhs',
      logged_in: false,
      account: null,
      need_sms: false,
      message: '小红书未登录，去「账号登录」扫码后再发',
      verified_at: null,
    },
    notice: '',
    ...p,
  }
}

/** 三种登录态各来一个，其余凑满 7 平台 */
const ITEMS: AccountItem[] = [
  item({
    platform: 'xhs',
    auth: {
      platform: 'xhs', logged_in: true, account: '@ai', need_sms: false,
      message: '小红书登录态有效（@ai）', verified_at: '2026-10-01T08:00:00Z',
    },
  }),
  item({
    platform: 'dy',
    display_name: '抖音',
    forms: ['video'],
    title_max: 55,
    body_max: 55,
    has_credential: true,
    auth: {
      platform: 'dy', logged_in: false, account: '@ai', need_sms: false,
      message: '抖音登录态已过期，需重新扫码', verified_at: '2026-09-01T08:00:00Z',
    },
  }),
  item({ platform: 'gzh', display_name: '微信公众号', forms: ['image', 'text'], title_max: 64, body_max: 20000 }),
  item({
    platform: 'ks', display_name: '快手', forms: ['image', 'video'], title_max: 20, body_max: 1000,
    notice: '上限按公开资料设定',
  }),
  item({ platform: 'zhihu', display_name: '知乎', forms: ['text'], title_max: 100, body_max: 20000 }),
  item({ platform: 'bilibili', display_name: 'B站', forms: ['video'], title_max: 80, body_max: 2000 }),
  item({ platform: 'wcs', display_name: '微信视频号', forms: ['video'], title_max: 16, body_max: 1000 }),
]

const RESPONSE: AccountsResponse = {
  items: ITEMS,
  total: 7,
  qr_login: {
    supported: false,
    notice: '扫码登录需要本机浏览器自动化与真实账号环境（平台风控限制），当前支持凭证登录 + 登录态标记',
  },
  verify_notice: '登录态校验读取本地凭证状态；真实有效性以发布时平台反馈为准（当前发布为 dry-run）',
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/accounts']}>
      <AccountsPage />
      <ToastHost />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  apiMock.get.mockReset()
  apiMock.post.mockReset()
  apiMock.patch.mockReset()
  apiMock.del.mockReset()
  apiMock.get.mockResolvedValue(RESPONSE)
})

describe('账号登录 · 平台卡渲染（F-G22）', () => {
  it('渲染 7 张平台卡 + 固定两条 notice', async () => {
    renderPage()
    await waitFor(() => expect(screen.getAllByTestId(/^acct-/)).toHaveLength(7))
    // 两条固定 notice（扫码诚实不可用 + 验证诚实说明）
    expect(screen.getByText(/扫码登录需要本机浏览器自动化与真实账号环境/)).toBeInTheDocument()
    expect(screen.getByText(/真实有效性以发布时平台反馈为准/)).toBeInTheDocument()
  })

  it('登录态三色标：已登录 / 已过期 / 未验证或未登录；新平台带 notice 小字', async () => {
    renderPage()
    const xhs = await screen.findByTestId('acct-xhs')
    expect(within(xhs).getByText('已登录')).toBeInTheDocument()
    expect(within(xhs).getByText('图文')).toBeInTheDocument()
    expect(within(xhs).getByText('视频')).toBeInTheDocument()
    expect(within(xhs).getByText(/最近验证/)).toBeInTheDocument()

    const dy = screen.getByTestId('acct-dy')
    expect(within(dy).getByText('已过期')).toBeInTheDocument()

    const gzh = screen.getByTestId('acct-gzh')
    expect(within(gzh).getByText('未验证或未登录')).toBeInTheDocument()
    expect(within(gzh).getByText(/标题 ≤ 64 字 · 正文 ≤ 20000 字/)).toBeInTheDocument()

    const ks = screen.getByTestId('acct-ks')
    expect(within(ks).getByText('上限按公开资料设定')).toBeInTheDocument()
  })
})

describe('账号登录 · 录入凭证（F-G25）', () => {
  it('弹层发请求体（account + secret）', async () => {
    const user = userEvent.setup()
    apiMock.post.mockResolvedValueOnce({
      ok: true, unchanged: false,
      credential: { account: '@ai', state: 'unknown', verified_at: '', secret_masked: 'sk-****abcd' },
    })
    renderPage()
    const xhs = await screen.findByTestId('acct-xhs')
    await user.click(within(xhs).getByRole('button', { name: '录入凭证' }))
    const dialog = await screen.findByRole('dialog')
    // 账号回显当前登录账号；改写后再保存
    const accountInput = within(dialog).getByLabelText('账号（可选）') as HTMLInputElement
    expect(accountInput.value).toBe('@ai')
    await user.clear(accountInput)
    await user.type(accountInput, '@new')
    await user.type(within(dialog).getByLabelText('登录凭证 secret'), 'secret-123')
    expect(within(dialog).getByText(/留空保存=不覆盖/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: '保存凭证' }))
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        '/accounts/xhs/credential',
        { account: '@new', secret: 'secret-123' },
        expect.anything(),
      ),
    )
  })

  it('secret 留空 + 已有凭证 → 后端 unchanged → 「未改动」toast', async () => {
    const user = userEvent.setup()
    apiMock.post.mockResolvedValueOnce({
      ok: true, unchanged: true,
      credential: { account: '@ai', state: 'unknown', verified_at: '', secret_masked: 'sk-****abcd' },
    })
    renderPage()
    const dy = await screen.findByTestId('acct-dy')
    await user.click(within(dy).getByRole('button', { name: '录入凭证' }))
    const dialog = await screen.findByRole('dialog')
    // 不填 secret，直接保存
    await user.click(within(dialog).getByRole('button', { name: '保存凭证' }))
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        '/accounts/dy/credential',
        { account: '@ai' },
        expect.anything(),
      ),
    )
    await waitFor(() => {
      const toastText = document.querySelector('[data-testid="toasts"]')?.textContent ?? ''
      expect(toastText).toContain('未改动')
    })
  })
})

describe('账号登录 · 登出（F-G26）', () => {
  it('确认弹窗出现且文案含后果；确认后调 DELETE', async () => {
    const user = userEvent.setup()
    apiMock.del.mockResolvedValueOnce({ ok: true, platform: 'dy', logged_out: true })
    renderPage()
    const dy = await screen.findByTestId('acct-dy')
    await user.click(within(dy).getByRole('button', { name: '登出' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent(/将清除抖音的登录凭证与状态/)
    expect(dialog).toHaveTextContent(/不可恢复/)
    await user.click(within(dialog).getByRole('button', { name: '确认登出' }))
    await waitFor(() => expect(apiMock.del).toHaveBeenCalledWith('/accounts/dy'))
  })
})

describe('账号登录 · F-G28 窗口聚焦刷新', () => {
  it('visibilitychange → visible 时重拉列表', async () => {
    renderPage()
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(1))
    // jsdom 默认即 visible，这里显式钉住语义
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(2))
  })
})
