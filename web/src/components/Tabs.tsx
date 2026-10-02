import type { ReactNode } from 'react'

export type TabItem = {
  key: string
  label: ReactNode
  count?: number
  disabled?: boolean
}

export type TabsProps = {
  items: TabItem[]
  value: string
  onChange: (key: string) => void
  ariaLabel?: string
  className?: string
}

/** 标签页：容器 --surface-2，选中项白底 + 微阴影（UI-SPEC §4） */
export function Tabs({ items, value, onChange, ariaLabel = '标签页', className = '' }: TabsProps) {
  return (
    <div className={['tabs', className].filter(Boolean).join(' ')} role="tablist" aria-label={ariaLabel}>
      {items.map((it) => (
        <button
          key={it.key}
          type="button"
          role="tab"
          aria-selected={it.key === value}
          className={`tab ${it.key === value ? 'on' : ''}`}
          disabled={it.disabled}
          onClick={() => onChange(it.key)}
        >
          {it.label}
          {it.count != null ? <span className="mut2">{it.count}</span> : null}
        </button>
      ))}
    </div>
  )
}

export default Tabs
