export type BadgeTone = 'warn' | 'danger'

export type BadgeProps = {
  tone?: BadgeTone
  /** lg = 技能卡右上角的缺配置角标（19px，带阴影） */
  lg?: boolean
  children: React.ReactNode
  title?: string
  className?: string
  style?: React.CSSProperties
}

/** 16px 圆点徽标，只用于「缺配置 / 阻塞」这类状态（UI-SPEC §4） */
export function Badge({ tone = 'warn', lg, children, title, className = '', style }: BadgeProps) {
  return (
    <span
      className={['badge', tone, lg ? 'lg' : '', className].filter(Boolean).join(' ')}
      title={title}
      style={style}
    >
      {children}
    </span>
  )
}

export default Badge
