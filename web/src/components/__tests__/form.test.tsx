import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Input, Textarea, Field, Select } from '@/components'

describe('Input', () => {
  it('渲染 label / help 并可输入', async () => {
    const onChange = vi.fn()
    render(<Input label="AppID" help="只写不回传" onChange={onChange} />)
    const input = screen.getByLabelText('AppID')
    await userEvent.type(input, 'wx7f3')
    expect(onChange).toHaveBeenCalled()
    expect(screen.getByText('只写不回传')).toBeInTheDocument()
  })

  it('revealable 时默认掩码，点眼睛切回明文', async () => {
    render(<Input label="AppSecret" revealable defaultValue="e1a4c93b7d2f" />)
    const input = screen.getByLabelText('AppSecret')
    expect(input).toHaveAttribute('type', 'password')
    await userEvent.click(screen.getByRole('button', { name: '显示内容' }))
    expect(screen.getByLabelText('AppSecret')).toHaveAttribute('type', 'text')
  })

  it('error 优先于 help 展示', () => {
    render(<Input label="标题" help="建议 100–300 字" error="不能为空" />)
    expect(screen.getByText('不能为空')).toBeInTheDocument()
    expect(screen.queryByText('建议 100–300 字')).not.toBeInTheDocument()
  })
})

describe('Textarea', () => {
  it('渲染多行输入与字数提示', () => {
    render(<Textarea label="正文" rows={4} help="按 Enter 换行" />)
    expect(screen.getByLabelText('正文').tagName).toBe('TEXTAREA')
    expect(screen.getByText('按 Enter 换行')).toBeInTheDocument()
  })
})

describe('Field', () => {
  it('把 label 与控件通过 id 关联', () => {
    render(
      <Field label="标题" help="写清楚你到底是谁">
        {(id) => <input id={id} className="inp" />}
      </Field>,
    )
    expect(screen.getByLabelText('标题')).toBeInTheDocument()
    expect(screen.getByText('写清楚你到底是谁')).toBeInTheDocument()
  })
})

describe('Select', () => {
  it('渲染占位项与选项，可切换', async () => {
    const onChange = vi.fn()
    render(
      <Select
        label="平台"
        placeholder="请选择"
        options={[
          { value: 'xhs', label: '小红书' },
          { value: 'dy', label: '抖音' },
        ]}
        onChange={onChange}
      />,
    )
    const sel = screen.getByLabelText('平台')
    await userEvent.selectOptions(sel, 'dy')
    expect(onChange).toHaveBeenCalled()
    expect(sel).toHaveValue('dy')
  })
})
