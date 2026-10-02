/** SPEC-05 §4 · 内容库前端测试。
 *
 * 守住三条硬要求：
 * 1. HTML 预览进 `<iframe sandbox>`，**不授予同源权限**
 * 2. Markdown 渲染不注入原始 HTML
 * 3. 删除必须先取口令 + 逐字输入文件名，确认请求带 token
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { apiMock } = vi.hoisted(() => ({
  apiMock: { get: vi.fn(), post: vi.fn(), del: vi.fn() },
}))
vi.mock('@/lib/api', () => ({ api: apiMock }))

import { DeleteDialog } from '../DeleteDialog'
import { LibraryPage } from '../LibraryPage'
import { PreviewPane } from '../PreviewPane'
import { ProjectTree } from '../ProjectTree'
import type { LibFile } from '../types'

function file(over: Partial<LibFile> = {}): LibFile {
  return {
    name: 'post.html',
    path: 'demo/成品/post.html',
    rel_to_root: 'outputs/demo/成品/post.html',
    zone: '成品',
    kind: 'doc',
    ext: 'html',
    mime: 'text/html',
    size: 2048,
    size_human: '2.0 KB',
    width: null,
    height: null,
    duration: null,
    duration_human: null,
    modified_at: '2026-10-02 10:00',
    is_system: false,
    previewable: false,
    download_url: '/api/library/stream?path=demo',
    ...over,
  }
}

const PROJECT = {
  name: 'demo',
  path: 'demo',
  rel_to_root: 'outputs/demo',
  product_count: 3,
  material_count: 1,
  system_count: 2,
  file_count: 6,
  total_bytes: 120000,
  total_size_human: '117.2 KB',
  updated_at: '2026-10-02 10:00',
}

const TREE = {
  project: 'demo',
  zone: '成品',
  sub: '',
  path: 'demo/成品',
  rel_to_root: 'outputs/demo/成品',
  breadcrumb: [
    { label: 'demo', project: 'demo', zone: '', sub: '', path: 'demo' },
    { label: '成品', project: 'demo', zone: '成品', sub: '', path: 'demo/成品' },
  ],
  dirs: [{ name: 'xhs-card', path: 'demo/成品/xhs-card', rel_to_root: '', kind: 'dir' as const, is_system: false }],
  files: [file()],
  count: 1,
  is_system: false,
  orphan_removed: 0,
}

beforeEach(() => {
  vi.clearAllMocks()
  apiMock.get.mockImplementation((url: string) => {
    if (url.startsWith('/library/projects')) {
      return Promise.resolve({ projects: [PROJECT], count: 1, root: 'outputs', zones: ['成品', '素材', '.session'] })
    }
    if (url.startsWith('/library/tree')) return Promise.resolve(TREE)
    if (url.startsWith('/library/files')) return Promise.resolve({ files: [file()], count: 1, orphan_removed: 0 })
    if (url.startsWith('/library/preview')) {
      return Promise.resolve({
        path: 'demo/成品/note.md',
        name: 'note.md',
        format: 'markdown',
        content: '# 标题\n\n正文\n\n<script>window.__pwned = true</script>\n',
        truncated: false,
        size_human: '20 B',
        hint: null,
        is_system: false,
      })
    }
    return Promise.resolve({})
  })
  apiMock.post.mockImplementation((url: string) => {
    if (url === '/library/confirm-token') {
      return Promise.resolve({
        token: 'tok-123',
        expires_in: 300,
        target: 'file:demo/成品/post.html',
        warning: '你正在删除 `post.html` 及其全部内容',
        requires_typing: 'post.html',
        name: 'post.html',
        size: 2048,
        size_human: '2.0 KB',
      })
    }
    return Promise.resolve({ unlocked: false, enabled: false, notice: '受系统保护', message: 'M1 未开放' })
  })
  apiMock.del.mockResolvedValue({ ok: true, statement: '已删除 post.html 及其全部内容' })
})

describe('预览安全（F-G5 / SPEC-05 §4）', () => {
  it('HTML 预览渲染在 sandbox iframe 里，且不授予同源权限', () => {
    const { container } = render(<PreviewPane file={file()} />)
    const iframe = container.querySelector('iframe')
    expect(iframe).not.toBeNull()
    // 属性必须存在且为空（全能力禁用）
    expect(iframe?.hasAttribute('sandbox')).toBe(true)
    const sandbox = iframe?.getAttribute('sandbox') ?? ''
    expect(sandbox).toBe('')
    expect(sandbox).not.toContain('allow-same-origin')
    expect(sandbox).not.toContain('allow-scripts')
    // 媒体 src 统一走 stream（Range）
    expect(iframe?.getAttribute('src')).toBe('/api/library/stream?path=demo%2F%E6%88%90%E5%93%81%2Fpost.html')
  })

  it('Markdown 用 react-markdown 渲染，不注入原始 HTML', async () => {
    const { container } = render(
      <PreviewPane file={file({ name: 'note.md', path: 'demo/成品/note.md', ext: 'md', previewable: true })} />,
    )
    await waitFor(() => expect(screen.getByRole('heading', { name: '标题' })).toBeInTheDocument())
    expect(container.querySelector('h1')?.textContent).toBe('标题')
    // 原始 <script> 不能变成真节点
    expect(container.querySelector('script')).toBeNull()
    expect(container.innerHTML).toContain('&lt;script&gt;')
  })

  it('图片与视频的 src 指向 stream 端点', () => {
    const { container: c1 } = render(<PreviewPane file={file({ name: 'a.png', path: 'p/a.png', ext: 'png', kind: 'image' })} />)
    expect(c1.querySelector('img')?.getAttribute('src')).toContain('/api/library/stream?path=')
    const { container: c2 } = render(<PreviewPane file={file({ name: 'a.mp4', path: 'p/a.mp4', ext: 'mp4', kind: 'video' })} />)
    expect(c2.querySelector('video')?.getAttribute('src')).toContain('/api/library/stream?path=')
  })
})

describe('删除保护（F-G7 / UI-SPEC 规则 19）', () => {
  it('必须逐字输入文件名才解锁，确认请求带 confirm token', async () => {
    const user = userEvent.setup()
    const onDeleted = vi.fn()
    render(
      <MemoryRouter>
        <DeleteDialog target={{ type: 'file', file: file() }} onClose={() => {}} onDeleted={onDeleted} />
      </MemoryRouter>,
    )

    // 文案必须显式声明后果
    await waitFor(() => expect(screen.getAllByText(/你正在删除 `post\.html` 及其全部内容/).length).toBeGreaterThan(0))

    const okBtn = screen.getByRole('button', { name: '确认删除' })
    expect(okBtn).toBeDisabled()

    await user.type(screen.getByLabelText(/二次确认/), 'post.htm')
    expect(screen.getByRole('button', { name: '确认删除' })).toBeDisabled()

    await user.type(screen.getByLabelText(/二次确认/), 'l')
    expect(screen.getByRole('button', { name: '确认删除' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: '确认删除' }))
    await waitFor(() => expect(apiMock.del).toHaveBeenCalledTimes(1))
    const url = apiMock.del.mock.calls[0][0] as string
    expect(url).toContain('confirm=tok-123')
    expect(url).toContain(encodeURIComponent('demo/成品/post.html'))
    expect(onDeleted).toHaveBeenCalled()
  })
})

describe('项目树（UI-SPEC 规则 20）', () => {
  it('.session 标「系统」chip 且置灰，商品分区不带', () => {
    render(
      <ProjectTree
        projects={[PROJECT]}
        current={{ project: 'demo', zone: '成品', sub: '' }}
        onProject={() => {}}
        onZone={() => {}}
        onSub={() => {}}
      />,
    )
    const session = screen.getByTestId('zone-.session')
    expect(session.textContent).toContain('系统')
    expect(session.style.color).toBe('var(--muted)')
    const product = screen.getByTestId('zone-成品')
    expect(product.textContent).not.toContain('系统')
    expect(product.textContent).toContain('3')
  })
})

describe('页面装配', () => {
  it('渲染面包屑、过滤 tab 与文件网格', async () => {
    render(
      <MemoryRouter>
        <LibraryPage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByTestId('file-grid')).toBeInTheDocument())
    expect(screen.getByText('demo / 成品')).toBeInTheDocument()
    expect(screen.getByTestId('tile-post.html')).toBeInTheDocument()
    for (const label of ['全部', '图片', '视频', '音频', '文档']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    }
    // 类型过滤切到视频后只请求 kind=video
    await userEvent.click(screen.getByRole('button', { name: '视频' }))
    await waitFor(() =>
      expect(
        apiMock.get.mock.calls.some((c) => String(c[0]).includes('kind=video')),
      ).toBe(true),
    )
  })
})
