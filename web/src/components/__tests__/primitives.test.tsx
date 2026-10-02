import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Button, Chip, Card, Tabs, Badge } from '@/components'
import { Check } from 'lucide-react'

describe('Button', () => {
  it('按 variant / size 渲染对应类名并触发点击', async () => {
    const onClick = vi.fn()
    render(
      <Button variant="primary" size="lg" onClick={onClick}>
        让 AI 帮我写今天的稿
      </Button>,
    )
    const btn = screen.getByRole('button', { name: '让 AI 帮我写今天的稿' })
    expect(btn.className).toContain('btn')
    expect(btn.className).toContain('pri')
    expect(btn.className).toContain('lg')
    await userEvent.click(btn)
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('disabledReason 禁用时显示原因 tooltip，且按钮不可点', async () => {
    render(
      <Button disabled disabledReason="缺 MINIMAX_API_KEY">
        运行
      </Button>,
    )
    const btn = screen.getByRole('button', { name: '运行' })
    expect(btn).toBeDisabled()
    expect(screen.getByRole('tooltip')).toHaveTextContent('缺 MINIMAX_API_KEY')
    expect(screen.getByRole('note')).toHaveAttribute('aria-label', '禁用原因：缺 MINIMAX_API_KEY')
    await userEvent.click(btn)
    expect(btn).toBeDisabled()
  })

  it('loading 时禁用并显示加载图标', () => {
    render(<Button loading>发送</Button>)
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled()
  })

  it('icon 传入时渲染图标并保持可访问名', () => {
    render(<Button icon={Check}>已连通</Button>)
    expect(screen.getByRole('button', { name: /已连通/ })).toBeInTheDocument()
  })
})

describe('Chip', () => {
  it('渲染语义色变体与 mono 变体', () => {
    render(
      <>
        <Chip tone="accent">门禁通过 2/2</Chip>
        <Chip tone="outline" mono>
          outputs/tool-dumb
        </Chip>
      </>,
    )
    expect(screen.getByText('门禁通过 2/2').className).toContain('a')
    expect(screen.getByText('outputs/tool-dumb').className).toContain('mono')
  })

  it('onClose 时可点 × 移除', async () => {
    const onClose = vi.fn()
    render(<Chip onClose={onClose}>参考对标.pdf</Chip>)
    await userEvent.click(screen.getByRole('button', { name: '移除' }))
    expect(onClose).toHaveBeenCalled()
  })
})

describe('Card', () => {
  it('渲染标题、操作区与卡片体', () => {
    render(
      <Card title="今日待办" actions={<button type="button">3 项</button>}>
        <p>内容</p>
      </Card>,
    )
    expect(screen.getByText('今日待办')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '3 项' })).toBeInTheDocument()
    expect(screen.getByText('内容')).toBeInTheDocument()
  })

  it('tight 时卡片体内边距收紧', () => {
    const { container } = render(<Card tight>内容</Card>)
    expect(container.querySelector('.card-b')?.className).toContain('tight')
  })
})

describe('Tabs', () => {
  it('当前项高亮，点击切换并回调', async () => {
    const onChange = vi.fn()
    render(
      <Tabs
        items={[
          { key: 'all', label: '全部', count: 20 },
          { key: 'v0', label: '已验证' },
        ]}
        value="all"
        onChange={onChange}
      />,
    )
    expect(screen.getByRole('tab', { name: /全部/ })).toHaveAttribute('aria-selected', 'true')
    await userEvent.click(screen.getByRole('tab', { name: '已验证' }))
    expect(onChange).toHaveBeenCalledWith('v0')
  })
})

describe('Badge', () => {
  it('缺配置角标渲染为警告态', () => {
    render(<Badge tone="warn">!</Badge>)
    expect(screen.getByText('!').className).toContain('w')
  })
})
