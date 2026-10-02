import type { ReactNode } from 'react'

export type Column<T> = {
  key: string
  /** 表头内容；传入 'num' 样式请用 numeric */
  title: ReactNode
  numeric?: boolean
  width?: number | string
  render?: (row: T, index: number) => ReactNode
}

export type TableProps<T> = {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T, index: number) => string
  caption?: string
  empty?: ReactNode
  className?: string
}

/** 数据表：11px 大写表头 + --line-soft 行分隔，数字列右对齐等宽（UI-SPEC §4） */
export function Table<T>({ columns, rows, rowKey, caption, empty, className = '' }: TableProps<T>) {
  return (
    <div className={['tbl-wrap', className].filter(Boolean).join(' ')}>
      <table className="tbl">
        {caption ? <caption className="help" style={{ textAlign: 'left', paddingBottom: 8 }}>{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={c.numeric ? 'num' : undefined} style={c.width ? { width: c.width } : undefined}>
                {c.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} style={{ color: 'var(--muted)' }}>
                {empty ?? '暂无数据'}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr key={rowKey(row, i)}>
                {columns.map((c) => (
                  <td key={c.key} className={c.numeric ? 'num' : undefined}>
                    {c.render ? c.render(row, i) : String((row as Record<string, unknown>)[c.key] ?? '')}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

export default Table
