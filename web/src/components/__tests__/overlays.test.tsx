import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ConfirmDialog, Drawer, EmptyState, Modal, Skeleton, ToastHost, pushToast, toast } from '@/components'

describe('ConfirmDialog', () => {
  it('requireTyping 未输入时禁用确认按钮并说明原因', async () => {
    const onConfirm = vi.fn()
    render(
      <ConfirmDialog
        open
        title="确认删除？"
        sub="删除后无法从内容库恢复"
        requireTyping="card-01.png"
        okText="删除 1 个文件"
        danger
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />,
    )
    const ok = screen.getByRole('button', { name: '删除 1 个文件' })
    expect(ok).toBeDisabled()
    expect(screen.getByText('请输入 card-01.png 以确认')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText(/二次确认/), 'card-01.png')
    // 输入正确后 tooltip 包裹层消失、按钮重新挂载，需重新查询
    const okReady = screen.getByRole('button', { name: '删除 1 个文件' })
    expect(okReady).toBeEnabled()
    await userEvent.click(okReady)
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('普通二次确认：取消不会触发 onConfirm', async () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(
      <ConfirmDialog open title="确认发布到 2 个平台？" onCancel={onCancel} onConfirm={onConfirm} okText="确认发布" />,
    )
    expect(screen.getByText('确认发布到 2 个平台？')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '再想想' }))
    expect(onCancel).toHaveBeenCalled()
    expect(onConfirm).not.toHaveBeenCalled()
  })
})

describe('Modal', () => {
  it('open 时渲染标题与正文，Esc 可关闭', async () => {
    const onClose = vi.fn()
    render(
      <Modal open title="深度加载抖音增量？" onClose={onClose} okText="我知道代价，继续">
        <p>预计 40–70 秒</p>
      </Modal>,
    )
    expect(screen.getByText('预计 40–70 秒')).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })

  it('关闭时不渲染对话框', () => {
    render(<Modal open={false} title="x" onClose={vi.fn()} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('Drawer', () => {
  it('open 时渲染标题、元信息与底部操作区', () => {
    render(
      <Drawer
        open
        onClose={vi.fn()}
        title="一键成片"
        meta={<span>skill/one-video</span>}
        footer={<button type="button">运行</button>}
      >
        <p>流水线</p>
      </Drawer>,
    )
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('一键成片')).toBeInTheDocument()
    expect(screen.getByText('skill/one-video')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '运行' })).toBeInTheDocument()
  })
})

describe('EmptyState', () => {
  it('必须给出下一步动作：标题 + 说明 + 按钮', async () => {
    const onAction = vi.fn()
    render(
      <EmptyState
        title="还没有收藏"
        description="在上面的热榜里点「收藏」，会带来源存进选题库。"
        actionLabel="去热点发现"
        onAction={onAction}
      />,
    )
    expect(screen.getByText('还没有收藏')).toBeInTheDocument()
    expect(screen.getByText(/在上面的热榜里点/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '去热点发现' }))
    expect(onAction).toHaveBeenCalled()
  })

  it('接受自定义 action 节点', () => {
    render(<EmptyState title="还没有接内容库" action={<button type="button">去内容库</button>} />)
    expect(screen.getByRole('button', { name: '去内容库' })).toBeInTheDocument()
  })
})

describe('Toast', () => {
  it('pushToast 后右下角出现提示并带状态', async () => {
    render(<ToastHost />)
    pushToast('已存入选题库 · 来源可溯源', 'ok')
    await waitFor(() => expect(screen.getByText('已存入选题库 · 来源可溯源')).toBeInTheDocument())
    expect(screen.getByTestId('toasts').querySelector('.toast')?.className).toContain('ok')
  })

  it('toast.error 走错误态', async () => {
    render(<ToastHost />)
    toast.error('硬门禁未通过：抖音标题 61/55 字')
    await waitFor(() => expect(screen.getByText(/硬门禁未通过/)).toBeInTheDocument())
  })
})

describe('Skeleton', () => {
  it('渲染占位块', () => {
    const { container } = render(<Skeleton width={120} height={12} />)
    expect(container.querySelector('.skel')).toHaveStyle({ width: '120px', height: '12px' })
  })
})
