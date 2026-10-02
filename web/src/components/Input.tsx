import { forwardRef, useId, useState } from 'react'
import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { Eye, EyeOff } from 'lucide-react'

type BaseProps = {
  label?: string
  help?: string
  error?: string
  mono?: boolean
  sizeSm?: boolean
  /** 密钥类输入：掩码回显 + 眼睛切换（UI-SPEC 规则 4） */
  revealable?: boolean
  width?: number | string
}

export type InputProps = BaseProps & InputHTMLAttributes<HTMLInputElement>
export type TextareaProps = BaseProps & TextareaHTMLAttributes<HTMLTextAreaElement>

function Shell({
  id,
  label,
  help,
  error,
  children,
}: {
  id: string
  label?: string
  help?: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <div className="field">
      {label ? <label htmlFor={id}>{label}</label> : null}
      {children}
      {error ? <span className="err">{error}</span> : help ? <span className="help">{help}</span> : null}
    </div>
  )
}

/** 34px 高输入框；聚焦 3px --accent-soft 光环 */
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, help, error, mono, sizeSm, revealable, width, className = '', id, ...rest },
  ref,
) {
  const auto = useId()
  const inputId = id ?? auto
  const [shown, setShown] = useState(false)
  const cls = ['inp', mono ? 'mono' : '', sizeSm ? 'sm' : '', className].filter(Boolean).join(' ')
  const input = (
    <input
      ref={ref}
      id={inputId}
      className={cls}
      style={width ? { width, ...(rest.style ?? {}) } : rest.style}
      type={revealable ? (shown ? 'text' : 'password') : rest.type}
      aria-invalid={error ? true : undefined}
      {...rest}
    />
  )
  const body = revealable ? (
    <div className="key-in">
      {input}
      <button
        type="button"
        className="eye"
        aria-label={shown ? '隐藏内容' : '显示内容'}
        onClick={() => setShown((s) => !s)}
      >
        {shown ? <EyeOff size={14} /> : <Eye size={14} />}
      </button>
    </div>
  ) : (
    input
  )
  return (
    <Shell id={inputId} label={label} help={help} error={error}>
      {body}
    </Shell>
  )
})

/** 多行输入；行高 1.6、可纵向拉伸 */
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, help, error, mono, className = '', id, ...rest },
  ref,
) {
  const auto = useId()
  const inputId = id ?? auto
  const cls = ['inp', mono ? 'mono' : '', className].filter(Boolean).join(' ')
  return (
    <Shell id={inputId} label={label} help={help} error={error}>
      <textarea ref={ref} id={inputId} className={cls} aria-invalid={error ? true : undefined} {...rest} />
    </Shell>
  )
})

export default Input
