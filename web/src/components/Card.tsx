import type { ReactNode } from 'react'

export type CardProps = {
  title?: ReactNode
  /** 卡片头右侧操作区 */
  actions?: ReactNode
  /** 卡片体去掉一部分内边距（列表型内容用） */
  tight?: boolean
  /** 卡片体自定义内边距，如 '4px 16px 8px' */
  bodyStyle?: React.CSSProperties
  bodyClassName?: string
  headerStyle?: React.CSSProperties
  className?: string
  children?: ReactNode
}

/** 卡片：白底 + --line 边 + 14px 圆角 + 基础阴影 */
export function Card({ title, actions, tight, bodyStyle, bodyClassName, headerStyle, className = '', children }: CardProps) {
  return (
    <section className={['card', className].filter(Boolean).join(' ')}>
      {title != null || actions != null ? (
        <header className="card-h" style={headerStyle}>
          {title != null ? <h3>{title}</h3> : null}
          {actions != null ? <div className="sp">{actions}</div> : null}
        </header>
      ) : null}
      <div
        className={['card-b', tight ? 'tight' : '', bodyClassName ?? ''].filter(Boolean).join(' ')}
        style={bodyStyle}
      >
        {children}
      </div>
    </section>
  )
}

export default Card
