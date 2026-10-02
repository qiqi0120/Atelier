/** 门禁报告形状与弹层内错误文案（后端契约 SPEC-01 §2 / PRD 原则二）。
 *
 * 从 features/topics/describe.ts 上移（SPEC-09）：日历建议弹层同样要渲染
 * gate_items 的 BLOCK 改法，门禁报告是 API 契约的一部分，归 lib。
 */

import { ApiError } from './api'

export type GateItemT = {
  gate: string
  label: string
  severity: 'block' | 'warn'
  passed: boolean
  actual: number | string | null
  limit: number | string | null
  message: string
  fix_hint: string | null
}

export type GateReportT = {
  blocked: boolean
  items: GateItemT[]
  summary: { total: number; failed: number; blocked_items: number; warn_items: number }
}

/** 弹层内错误文案：门禁 BLOCK 逐项带改法（PRD 原则二：命中即告知怎么修）。 */
export function describeError(e: unknown): string {
  if (!(e instanceof ApiError)) return String(e)
  const detail = e.detail as { gate_items?: GateItemT[] } | null
  const blocked = (detail?.gate_items ?? []).filter((i) => !i.passed && i.severity === 'block')
  if (blocked.length) {
    const lines = blocked.map((i) => `· ${i.message}${i.fix_hint ? `（改法：${i.fix_hint}）` : ''}`)
    return [e.message, ...lines].join('\n')
  }
  return e.display
}
