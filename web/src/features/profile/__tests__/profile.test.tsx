/* =============================================================================
   账号画像域前端测试（spec §6 交互规则 + 验收 3/7 的 UI 口径）
   fetch 全部打桩，验证**组件行为**而不是后端。
   ========================================================================== */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ProfilePage } from '@/features/profile'
import { ToastHost } from '@/components'
import { setToastSink } from '@/lib/api'
import type { Memory } from '@/lib/types'
import type { ProfileDetail } from '../api'

const BASE = '2026-10-01T12:00:00Z'

function detail(over: Partial<ProfileDetail> = {}): ProfileDetail {
  return {
    id: 'ai-efficiency',
    name: 'AI 效率观察',
    platforms: ['小红书', '抖音'],
    identity: '独立内容创作者，主力做 AI 效率',
    style: '短句为主，先给结论',
    audience: '22-32 岁的内容从业者',
    platform_rules: '小红书图文 1000 字',
    preferences: '- 不用极限词\n- 不做未实测的对比',
    memories: [],
    general_mode: false,
    created_at: BASE,
    updated_at: BASE,
    completeness: { identity: 100, style: 92, audience: 78, platform_rules: 100, preferences: 85, memories: 0 },
    completeness_overall: 76,
    dimension_labels: {},
    md_path: 'profiles/ai-efficiency.md',
    ...over,
  }
}

let state: ProfileDetail
/** PATCH 收到的请求体，用来断言「只提交被改的那一维」 */
let patched: Record<string, unknown>[] = []
/** 向导已完成的步数（stub 自己的状态机） */
let wizardDone = 0
const STEP_ORDER = ['basic', 'social', 'intent', 'redlines']

function jsonRoute(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

function mockFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    if (url.endsWith('/api/profiles') && method === 'GET') {
      return jsonRoute({
        profiles: [
          {
            id: state.id,
            name: state.name,
            platforms: state.platforms,
            general_mode: state.general_mode,
            completeness: state.completeness,
            completeness_overall: state.completeness_overall,
            memory_count: state.memories.length,
            created_at: state.created_at,
            updated_at: state.updated_at,
          },
        ],
        count: 1,
      })
    }
    if (/\/api\/profiles\/[^/]+$/.test(url) && method === 'GET') return jsonRoute(state)
    if (/\/api\/profiles\/[^/]+$/.test(url) && method === 'PATCH') {
      patched.push(JSON.parse(String(init?.body ?? '{}')))
      return jsonRoute({ ...state, ...JSON.parse(String(init?.body ?? '{}')) })
    }
    if (url.includes('/preview')) {
      return jsonRoute({
        profile_id: state.id,
        system_prompt: state.general_mode ? 'BASE ONLY' : `BASE + ${state.identity}`,
        prefix: state.general_mode ? '' : state.identity,
        base: 'BASE',
        suffix: '【流程提醒】先查技能库',
        general_mode: state.general_mode,
        injected: !state.general_mode,
        reason: state.general_mode ? '通用模式已开启' : '画像已内联',
        leaked_dims: [],
        prefix_chars: state.general_mode ? 0 : 10,
      })
    }
    if (url.includes('/general-mode') && method === 'POST') {
      const { enabled } = JSON.parse(String(init?.body ?? '{}')) as { enabled: boolean }
      state = { ...state, general_mode: enabled }
      return jsonRoute({ ...state, message: 'ok' })
    }
    if (url.includes('/memories') && method === 'POST') {
      const { text } = JSON.parse(String(init?.body ?? '{}')) as { text: string }
      const memory: Memory = { id: 'mem-1', text, source: '手动', created_at: BASE, adopted: true }
      state = { ...state, memories: [...state.memories, memory] }
      return jsonRoute({ ok: true, memory, message: '已记住' })
    }
    if (url.includes('/memories/') && method === 'DELETE') {
      state = { ...state, memories: state.memories.filter((m: Memory) => !url.endsWith(m.id)) }
      return jsonRoute({ ok: true })
    }
    if (url.includes('/wizard/step') && method === 'POST') {
      const body = JSON.parse(String(init?.body ?? '{}')) as { step: string; skip?: boolean }
      const skipped: string[] = []
      if (body.step === 'done') {
        wizardDone = 4
      } else {
        // 走完这一步就 +1（跳过的步同样 +1，这是 spec 的「跳过也前进」）
        if (wizardDone < STEP_ORDER.length) {
          if (body.skip) skipped.push(STEP_ORDER[wizardDone])
          wizardDone += 1
        }
      }
      const finished = wizardDone >= STEP_ORDER.length
      return jsonRoute({
        token: 'tok-1',
        profile_id: state.id,
        completed: wizardDone,
        progress: wizardDone,
        progress_label: `${wizardDone}/4`,
        next_step: finished ? 'done' : STEP_ORDER[wizardDone],
        skipped,
        finished,
        profile: state,
      })
    }
    if (url.includes('/wizard?') && method === 'GET') {
      return jsonRoute({
        token: 'tok-1',
        profile_id: state.id,
        completed: wizardDone,
        progress: wizardDone,
        progress_label: `${wizardDone}/4`,
        next_step: 'basic',
        skipped: [],
        finished: false,
        steps: [
          { key: 'basic', index: 1, title: '基础信息', sub: '', fields: [], skippable: false, hint: '只填账号名就能继续' },
          { key: 'social', index: 2, title: '社媒链接', sub: '', fields: [], skippable: true, hint: '先跳过也行' },
          { key: 'intent', index: 3, title: '运营意图', sub: '', fields: [], skippable: true, hint: '' },
          { key: 'redlines', index: 4, title: '偏好红线', sub: '', fields: [], skippable: true, hint: '' },
        ],
      })
    }
    if (url.includes('/wizard?') && method === 'DELETE') {
      return jsonRoute({ abandoned: true, profile_id: state.id, kept: true, profile: state })
    }
    if (url.endsWith('/api/profiles') && method === 'POST') {
      return jsonRoute({ ...detail({ id: 'new-one' }), wizard_token: 'tok-1' }, 201)
    }
    return jsonRoute({ error: { code: 'NotFound', message: 'no stub', detail: {}, hint: null } }, 404)
  })
}

/** 卡片标题在左导航和卡片头各有一份，这里精确取卡片头那个 <h3> */
function cardByTitle(title: string): HTMLElement {
  const h3 = screen.getAllByText(title).find((el) => el.tagName === 'H3')
  if (!h3) throw new Error(`找不到卡片「${title}」`)
  return h3.closest('.card') as HTMLElement
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ProfilePage />
      <ToastHost />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  state = detail()
  patched = []
  wizardDone = 0
  setToastSink((m, k) => {
    if (k === 'ok') void m
  })
  vi.stubGlobal('fetch', mockFetch())
  window.open = vi.fn() as unknown as typeof window.open
})

afterEach(() => {
  vi.unstubAllGlobals()
  setToastSink(null)
})

describe('ProfileEditor · 六维分栏编辑 + 实时预览', () => {
  it('渲染六维导航与完整度，并把当前维的正文放进编辑器', async () => {
    renderPage()

    // 左导航六项 + 完整度
    await waitFor(() => expect(screen.getByText('完整度 76%')).toBeInTheDocument())
    for (const name of ['定位', '风格', '受众', '平台', '偏好红线', '长期记忆']) {
      expect(screen.getByRole('button', { name: new RegExp(name) })).toBeInTheDocument()
    }
    // 默认停在「定位」，编辑区带的是 identity 的正文
    const editor = await screen.findByLabelText('编辑（Markdown）')
    expect(editor).toHaveValue('独立内容创作者，主力做 AI 效率')
  })

  it('编辑触发 300ms 防抖预览，保存只提交被改的那一维并给出 toast 文案', async () => {
    const user = userEvent.setup()
    renderPage()

    const editor = await screen.findByLabelText('编辑（Markdown）')
    await user.clear(editor)
    await user.type(editor, '新的定位写法')

    // 防抖窗口内预览还是旧内容
    const preview = screen.getByTestId('dim-preview')
    expect(preview).toHaveTextContent('独立内容创作者')

    // 300ms 后预览跟上
    await waitFor(() => expect(preview).toHaveTextContent('新的定位写法'), { timeout: 2000 })

    // 保存按钮从 disabled 变可用
    const save = screen.getByRole('button', { name: '保存' })
    await waitFor(() => expect(save).toBeEnabled())
    await user.click(save)

    await waitFor(() => expect(patched).toHaveLength(1))
    expect(patched[0]).toEqual({ identity: '新的定位写法' })
    expect(await screen.findByText('已保存 · 下一轮对话立即生效')).toBeInTheDocument()
  })

  it('切维度时切到「偏好红线」并列出可删的红线条目', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByLabelText('编辑（Markdown）')
    await user.click(screen.getByRole('button', { name: /偏好红线/ }))

    const editor = await screen.findByLabelText('编辑（Markdown）')
    expect(editor).toHaveValue('- 不用极限词\n- 不做未实测的对比')

    const card = cardByTitle('偏好红线')
    expect(within(card).getByText('不用极限词')).toBeInTheDocument()
    expect(within(card).getByText('不做未实测的对比')).toBeInTheDocument()

    await user.click(within(card).getByRole('button', { name: '删除红线：不用极限词' }))
    await waitFor(() =>
      expect(patched.some((p) => typeof p.preferences === 'string' && !String(p.preferences).includes('不用极限词'))).toBe(
        true,
      ),
    )
  })
})

describe('ProfilePage · 长期记忆与通用模式', () => {
  it('手动加一条记忆 → 立即出现在列表里', async () => {
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(cardByTitle('长期记忆')).toBeInTheDocument())
    await user.type(screen.getByLabelText('手动记一条'), '标题不要用极限词')
    await user.click(screen.getByRole('button', { name: '记下来' }))

    await waitFor(() => expect(screen.getByText('标题不要用极限词')).toBeInTheDocument())
    expect(screen.getByText('1 条')).toBeInTheDocument()
  })

  it('开启通用模式后能预览到「不含画像」的 system_prompt', async () => {
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(cardByTitle('通用模式')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: '开启' }))
    await waitFor(() => expect(state.general_mode).toBe(true))

    await user.click(screen.getByRole('button', { name: '预览 system_prompt' }))
    const promptBox = await screen.findByTestId('system-prompt')
    await waitFor(() => expect(promptBox).toHaveTextContent('BASE ONLY'))
    // 编辑器里还看得到画像正文（那是草稿），但**真正注入的**这一段里没有
    expect(promptBox).not.toHaveTextContent('独立内容创作者')
  })
})

describe('ProfileWizard · 4 步可跳过', () => {
  it('第 1 步没名字被拦下；之后每步都能「先跳过」且照样推进到 4/4', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('完整度 76%')
    await user.click(screen.getByRole('tab', { name: '＋ 新建' }))

    const dialog = await screen.findByRole('dialog')

    // 第 1 步不可跳过：没有「先跳过」按钮
    expect(within(dialog).queryByRole('button', { name: '先跳过' })).not.toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: '下一步' }))
    expect(await screen.findByText(/先给账号起个名字/)).toBeInTheDocument()
    // 进度没动
    expect(within(dialog).getByText('0/4')).toBeInTheDocument()

    await user.type(within(dialog).getByLabelText('账号名（必填）'), '咖啡探店日记')
    await user.click(within(dialog).getByRole('button', { name: '下一步' }))
    await waitFor(() => expect(within(dialog).getByText('1/4')).toBeInTheDocument())

    // 第 2 步起有「先跳过」，点两次推进到 3/4（**跳过也前进**）
    for (const expected of ['2/4', '3/4']) {
      const skip = await within(dialog).findByRole('button', { name: '先跳过' })
      await user.click(skip)
      await waitFor(() => expect(within(dialog).getByText(expected)).toBeInTheDocument())
    }

    // 最后一步跳过 → 服务端返回 4/4 + finished，向导自动收起
    await user.click(within(dialog).getByRole('button', { name: '先跳过' }))
    const stepCalls = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter((c) =>
      String(c[0]).includes('/wizard/step'),
    )
    const last = JSON.parse(String((stepCalls.at(-1)?.[1] as RequestInit).body))
    expect(last.step).toBe('redlines')
    expect(last.skip).toBe(true)

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(await screen.findByLabelText('编辑（Markdown）')).toBeInTheDocument()
  })

  it('中途放弃保留已填内容，不丢画像', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('完整度 76%')
    await user.click(screen.getByRole('tab', { name: '＋ 新建' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('账号名（必填）'), '咖啡探店日记')
    await user.click(within(dialog).getByRole('button', { name: '中途放弃' }))

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const abandonCall = (fetch as ReturnType<typeof vi.fn>).mock.calls.find(
      (c) => String(c[0]).includes('/wizard?') && (c[1] as RequestInit)?.method === 'DELETE',
    )
    expect(abandonCall).toBeTruthy()
    // 放弃后向导收起，但画像还在编辑页里
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(await screen.findByLabelText('编辑（Markdown）')).toBeInTheDocument()
  })
})
