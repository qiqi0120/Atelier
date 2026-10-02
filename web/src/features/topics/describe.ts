/** 弹层内错误文案：门禁 BLOCK 逐项带改法（PRD 原则二：命中即告知怎么修）。 */

import { ApiError } from '@/lib/api'
import type { GateItemT } from './types'

export function describeError(e: unknown): string {
  if (!(e instanceof ApiError)) return String(e)
  const detail = e.detail as { gate_items?: GateItemT[] } | null
  const blocked = (detail?.gate_items ?? []).filter((i) => !i.passed && i.severity === 'block')
  if (blocked.length) {
    const lines = blocked.map(
      (i) => `· ${i.message}${i.fix_hint ? `（改法：${i.fix_hint}）` : ''}`,
    )
    return [e.message, ...lines].join('\n')
  }
  return e.display
}
