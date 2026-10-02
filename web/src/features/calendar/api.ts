/** SPEC-09 §5 · 日历域 API client（唯一出口，只做 URL 拼装与类型标注）。 */

import { api } from '@/lib/api'
import type { CalEvent, CalKind, MonthView, SeedResult, SuggestResult, UpcomingResponse } from './types'

/** 写请求必须显式带 Content-Type：地基的跨站写中间件（SPEC-01 §8）要求。 */
const JSON_HEADERS = { 'Content-Type': 'application/json' } as const

export type CreateEventBody = {
  title: string
  date: string
  end_date?: string
  kind: CalKind
  note?: string
  remind_days?: number
}

export type PatchEventBody = Partial<CreateEventBody>

export type SuggestBody = { profile_id?: string; days?: number }

export const calendarApi = {
  month: (m = '') =>
    api.get<MonthView>(`/calendar${m ? `?month=${encodeURIComponent(m)}` : ''}`),

  upcoming: (days = 14) => api.get<UpcomingResponse>(`/calendar/upcoming?days=${days}`),

  seed: (year?: number) =>
    api.post<SeedResult>('/calendar/seed', year === undefined ? {} : { year }, { headers: JSON_HEADERS }),

  suggest: (body: SuggestBody) =>
    api.post<SuggestResult>('/calendar/suggest', body, { headers: JSON_HEADERS }),

  create: (body: CreateEventBody) =>
    api.post<CalEvent>('/calendar', body, { headers: JSON_HEADERS }),

  update: (id: string, changes: PatchEventBody) =>
    api.patch<CalEvent>(`/calendar/${id}`, changes, { headers: JSON_HEADERS }),

  remove: (id: string) =>
    api.del<{ ok: boolean; id: string }>(`/calendar/${id}`, { headers: JSON_HEADERS }),
}
