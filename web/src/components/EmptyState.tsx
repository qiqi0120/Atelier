import type { ReactNode } from 'react'

export type EmptyStateProps = {
  title: ReactNode
  /** 说明文案，max-width 320px 居中 */
  description?: ReactNode
  /**
   * 下一步动作（必填语义）。SPEC-07 §3：EmptyState 必须给出下一步动作。
   * 传字符串 → 渲染主按钮；传节点 → 原样渲染。
   */
  action?: ReactNode
  actionLabel?: string
  onAction?: () => void
  icon?: ReactNode
  className?: string
}

/** 空态：标题 14px + 说明 12.5px，必须带一个下一步动作（UI-SPEC §4） */
export function EmptyState({
  title,
  description,
  action,
  actionLabel,
  onAction,
  icon,
  className = '',
}: EmptyStateProps) {
  return (
    <div className={['empty', className].filter(Boolean).join(' ')}>
      {icon}
      <h4>{title}</h4>
      {description ? <p>{description}</p> : null}
      {action != null || (actionLabel && onAction) ? (
        <div className="empty-act">
          {action ??
            (actionLabel ? (
              <button type="button" className="btn pri" onClick={onAction}>
                <span className="btn-txt">{actionLabel}</span>
              </button>
            ) : null)}
        </div>
      ) : null}
    </div>
  )
}

export default EmptyState
