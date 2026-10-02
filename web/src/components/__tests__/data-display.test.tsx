import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Avatar, ProgressBar, Table, Chip } from '@/components'

type Row = { name: string; plays: number; verdict: string }

const ROWS: Row[] = [
  { name: 'AI 工具越用越笨', plays: 31200, verdict: '反常识钩子有效' },
  { name: '提示词模板合集', plays: 2100, verdict: '同质化' },
]

describe('Avatar', () => {
  it('截取前两字渲染文字标识', () => {
    const { container } = render(<Avatar label="效率" tone="accent" />)
    expect(container.textContent).toBe('效率')
    expect(container.querySelector('.avatar')?.className).toContain('g')
  })
})

describe('ProgressBar', () => {
  it('按百分比渲染并暴露 aria 值', () => {
    render(<ProgressBar value={62} label="小红书字数" />)
    const bar = screen.getByRole('progressbar', { name: '小红书字数' })
    expect(bar).toHaveAttribute('aria-valuenow', '62')
    expect(bar.querySelector('i')).toHaveStyle({ width: '62%' })
  })

  it('超限时走 danger 样式', () => {
    const { container } = render(<ProgressBar value={140} />)
    expect(container.querySelector('i')?.className).toContain('over')
  })
})

describe('Table', () => {
  const columns = [
    { key: 'name', title: '内容' },
    { key: 'plays', title: '播放', numeric: true },
    { key: 'verdict', title: '结构判定', render: (r: Row) => <Chip tone="accent">{r.verdict}</Chip> },
  ]

  it('渲染表头与数据行', () => {
    render(<Table columns={columns} rows={ROWS} rowKey={(r) => r.name} />)
    expect(screen.getByText('内容')).toBeInTheDocument()
    expect(screen.getByText('31200')).toBeInTheDocument()
    expect(screen.getByText('反常识钩子有效')).toBeInTheDocument()
  })

  it('空数据时渲染空态而不是白屏', () => {
    render(<Table columns={columns} rows={[]} rowKey={(r: Row) => r.name} empty="还没有数据" />)
    expect(screen.getByText('还没有数据')).toBeInTheDocument()
  })
})

describe('集成：门禁结果块', () => {
  it('PASS / WARN 分级样式正确', async () => {
    const { container } = render(
      <>
        <div className="gate">
          <div className="gi">
            小红书正文 782 / 1000 字 <span className="s pass">PASS</span>
          </div>
          <div className="gi">
            AI 味自检（5 维） 72 → 81 <span className="s warn">WARN</span>
          </div>
          <div className="gi">
            抖音标题 61 / 55 字 <span className="s block">BLOCK</span>
          </div>
        </div>
      </>,
    )
    const marks = Array.from(container.querySelectorAll('.gi .s')).map((n) => n.className)
    expect(marks).toEqual(['s pass', 's warn', 's block'])
    await userEvent.click(screen.getByText('PASS'))
  })
})
