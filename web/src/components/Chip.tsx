import type { ReactNode } from 'react'

export type ChipTone = 'neutral' | 'accent' | 'warn' | 'danger' | 'info' | 'outline' | 'on'
export type ChipProps = {
  tone?: ChipTone
  /** mono 变体用于 ID / 路径 / 数字读数 */
  mono?: boolean
  xs?: boolean
  icon?: ReactNode
  onClose?: () => void
  children?: ReactNode
  title?: string
  className?: string
  style?: React.CSSProperties
  onClick?: () => void
}

const TONE: Record<ChipTone, string> = {
  neutral: '',
  accent: 'a',
  warn: 'w',
  danger: 'd',
  info: 'i',
  outline: 'o',
  on: 'on',
}

/** 22px 高 / 20px 圆角的标签。UI-SPEC §4 变体 .a/.w/.d/.i/.o/.on */
export function Chip({ tone = 'neutral', mono, xs, icon, onClose, children, className = '', style, ...rest }: ChipProps) {
  const cls = ['chip', TONE[tone], mono ? 'mono' : '', xs ? 'xs' : '', className].filter(Boolean).join(' ')
  const Tag = rest.onClick ? 'button' : 'span'
  return (
    <Tag className={cls} style={style} title={rest.title} {...(rest.onClick ? { type: 'button', onClick: rest.onClick } : {})}>
      {icon}
      {children}
      {onClose ? (
        <span className="x" role="button" aria-label="移除" onClick={onClose}>
          ✕
        </span>
      ) : null}
    </Tag>
  )
}

export default Chip
