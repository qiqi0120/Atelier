export type ProgressBarProps = {
  /** 0–100，超出按超限样式渲染 */
  value: number
  over?: boolean
  sm?: boolean
  label?: string
  className?: string
}

/** 进度条：--surface-3 槽 + --accent 填充（超限转 --danger） */
export function ProgressBar({ value, over = false, sm = false, label, className = '' }: ProgressBarProps) {
  const v = Math.max(0, Math.min(100, value))
  const isOver = over || value > 100
  return (
    <div
      className={['prog', sm ? 'sm' : '', className].filter(Boolean).join(' ')}
      role="progressbar"
      aria-valuenow={Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ?? '进度'}
    >
      <i className={isOver ? 'over' : undefined} style={{ width: `${v}%` }} />
    </div>
  )
}

export default ProgressBar
