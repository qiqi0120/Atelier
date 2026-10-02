import { ShieldCheck } from 'lucide-react'
import type { GateItem, GateReport } from '@/lib/types'

export type GateBlockProps = { report: GateReport | null }

function severityOf(item: GateItem): 'pass' | 'warn' | 'block' {
  if (!item.passed) return item.severity === 'block' ? 'block' : 'warn'
  return 'pass'
}

function label(item: GateItem): string {
  const num = (v: number | string | null) => (v == null ? '' : v)
  const range = item.limit != null ? ` ${num(item.actual)} / ${num(item.limit)}` : item.actual != null ? ` ${num(item.actual)}` : ''
  return `${item.label}${range}`
}

/**
 * 门禁结果块：逐项 PASS / WARN / BLOCK（UI-SPEC 规则 9 / 原则二）。
 * 硬门禁红字阻断，软提醒只告警——这里只展示，不改内容。
 */
export function GateBlock({ report }: GateBlockProps) {
  if (!report || !report.items?.length) return null
  const failed = report.items.filter((i) => !i.passed).length
  const blocked = report.blocked ?? report.items.some((i) => i.severity === 'block' && !i.passed)
  return (
    <div className="gate">
      <div className="gh">
        <ShieldCheck size={13} />
        确定性门禁 · {blocked ? '未通过' : failed ? '有告警' : '已通过'}
      </div>
      {report.items.map((item, i) => {
        const s = severityOf(item)
        return (
          <div className="gi" key={`${item.gate}-${i}`} title={item.fix_hint ?? item.message}>
            <span>
              {label(item)}
              {s === 'pass' ? null : <span className="mut2"> · {item.message}</span>}
            </span>
            <span className={`s ${s}`}>{s.toUpperCase()}</span>
          </div>
        )
      })}
    </div>
  )
}

export default GateBlock
