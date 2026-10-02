/** SPEC-09 · 日历域类型（与后端 api/calendar.py 的响应形状一一对应）。
 *
 * 月视图里的「内容条目」复用选题域的 Topic 类型（日历只读展示，SPEC-09 §6）。
 */

import type { Topic } from '@/features/topics/types'

export type CalKind = 'festival' | 'ecommerce' | 'industry' | 'platform'
export type CalSource = 'builtin' | 'manual'

export type CalEvent = {
  id: string
  title: string
  date: string
  end_date: string
  kind: CalKind
  note: string
  remind_days: number
  source: CalSource
  created_at: string
  updated_at: string
}

/** 月视图：events = 日历节点（含跨月多日），topics = due_date 落当月的选题 */
export type MonthView = { month: string; events: CalEvent[]; topics: Topic[] }

export type UpcomingItem = CalEvent & { remind_active: boolean; days_left: number }
export type UpcomingResponse = { today: string; items: UpcomingItem[] }

export type SeedResult = { year: number; added: number; skipped: number }
export type SuggestResult = { items: Topic[]; count: number }

export const KIND_VALUES: CalKind[] = ['festival', 'ecommerce', 'industry', 'platform']

export const KIND_LABEL: Record<CalKind, string> = {
  festival: '节日',
  ecommerce: '电商节点',
  industry: '行业事件',
  platform: '平台活动',
}

/** 月格条目的文字前缀（kind 用文字标签区分，不引入新颜色——UI-SPEC §2） */
export const KIND_PREFIX: Record<CalKind, string> = {
  festival: '节',
  ecommerce: '促',
  industry: '业',
  platform: '活',
}

export const CAL_SOURCE_LABEL: Record<CalSource, string> = {
  builtin: '内置',
  manual: '手动',
}
