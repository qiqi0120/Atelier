import { forwardRef } from 'react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Loader2 } from 'lucide-react'

export type ButtonVariant = 'primary' | 'default' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md' | 'lg'

export type ButtonProps = {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  /** 禁用时必须说明原因，hover 显示 tooltip（UI-SPEC §4 / SPEC-07 §3） */
  disabledReason?: string
  icon?: LucideIcon
  iconRight?: LucideIcon
  block?: boolean
  children?: ReactNode
} & ButtonHTMLAttributes<HTMLButtonElement>

const VARIANT: Record<ButtonVariant, string> = {
  primary: 'pri',
  default: '',
  ghost: 'ghost',
  danger: 'danger',
}

/**
 * 主按钮 32px 高 / --accent 填充白字；禁用 45% 透明且必须配 disabledReason。
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'default',
    size = 'md',
    loading = false,
    disabledReason,
    icon: Icon,
    iconRight: IconRight,
    block = false,
    className = '',
    children,
    disabled,
    type = 'button',
    ...rest
  },
  ref,
) {
  const isDisabled = disabled || loading
  const cls = [
    'btn',
    VARIANT[variant],
    size !== 'md' ? size : '',
    block ? 'block' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  const btn = (
    <button
      ref={ref}
      type={type}
      className={cls}
      disabled={isDisabled}
      title={isDisabled && disabledReason ? disabledReason : rest.title}
      {...rest}
    >
      {loading ? <Loader2 size={13} className="spin" aria-hidden /> : Icon ? <Icon size={size === 'sm' ? 13 : 14} aria-hidden /> : null}
      {children != null && <span className="btn-txt">{children}</span>}
      {IconRight ? <IconRight size={13} aria-hidden /> : null}
    </button>
  )

  if (isDisabled && disabledReason) {
    return (
      <span className="btn-wrap" role="note" aria-label={`禁用原因：${disabledReason}`}>
        {btn}
        <span className="tool-tip" role="tooltip">
          {disabledReason}
        </span>
      </span>
    )
  }
  return btn
})

export default Button
