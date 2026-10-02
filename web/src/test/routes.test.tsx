import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AppShell } from '@/App'
import { setToastSink, ApiError, request } from '@/lib/api'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppShell />
    </MemoryRouter>,
  )
}

describe('外壳与路由（13 页）', () => {
  const ROUTES: [string, string][] = [
    ['/', '工作台'],
    ['/chat', '对话工作台'],
    ['/hot', '热点发现'],
    ['/capability', '能力地图'],
    ['/topics', '选题库'],
    ['/calendar', '内容日历'],
    ['/library', '内容库'],
    ['/publish', '发布中心'],
    ['/accounts', '账号登录'],
    ['/analytics', '数据复盘'],
    ['/profile', '账号画像'],
    ['/skills', '技能库'],
    ['/settings', '设置'],
  ]

  it.each(ROUTES)('%s 可访问且渲染页面标题，无白屏', async (path, title) => {
    const { container } = renderAt(path)
    await waitFor(() => expect(screen.getAllByText(title).length).toBeGreaterThan(0))
    expect(container.querySelector('.app')).toBeInTheDocument()
    expect(container.querySelector('.sidebar')).toBeInTheDocument()
    expect(container.querySelector('.topbar')).toBeInTheDocument()
  })

  it('未知路径渲染 404 提示而不是空白', async () => {
    renderAt('/nope')
    await waitFor(() => expect(screen.getByText('这个页面不存在')).toBeInTheDocument())
  })

  it('侧边栏按分组渲染 13 个入口，当前项高亮', async () => {
    const { container } = renderAt('/')
    const items = container.querySelectorAll('.nav-item')
    expect(items).toHaveLength(13)
    expect(container.querySelector('.nav-item.on')?.textContent).toContain('工作台')
    expect(container.querySelectorAll('.nav-label')).toHaveLength(4)
  })
})

describe('api.ts', () => {
  it('非 2xx 抛 ApiError 并解析后端错误体，同时自动 toast', async () => {
    const sink = vi.fn()
    setToastSink(sink)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify({ error: { code: 'GateBlocked', message: '硬门禁未通过', hint: '点「一键裁剪」自动修正' } }),
          { status: 422, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    await expect(request('/publish')).rejects.toBeInstanceOf(ApiError)
    await waitFor(() => expect(sink).toHaveBeenCalled())
    const msg = sink.mock.calls[0]?.[0] as string
    expect(msg).toContain('硬门禁未通过')
    expect(msg).toContain('一键裁剪')
    setToastSink(null)
    vi.unstubAllGlobals()
  })

  it('handled: true 时不自动 toast', async () => {
    const sink = vi.fn()
    setToastSink(sink)
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })))
    await expect(request('/x', { handled: true })).rejects.toBeInstanceOf(ApiError)
    expect(sink).not.toHaveBeenCalled()
    setToastSink(null)
    vi.unstubAllGlobals()
  })

  it('204 返回 undefined', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })))
    await expect(request('/library/x', { method: 'DELETE' })).resolves.toBeUndefined()
    vi.unstubAllGlobals()
  })
})
