/** SPEC-08 §5 · 选题域 API client（唯一出口，只做 URL 拼装与类型标注）。 */

import { api } from '@/lib/api'
import type {
  DecodeResult,
  HooksResult,
  MatrixResult,
  ScoreResult,
  Topic,
  TopicsResponse,
  TopicScore,
  TopicStatus,
} from './types'

/** 写请求必须显式带 Content-Type：地基的跨站写中间件（SPEC-01 §8）要求。 */
const JSON_HEADERS = { 'Content-Type': 'application/json' } as const

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === '') continue
    sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

export type CreateTopicBody = {
  title: string
  angle?: string
  profile_id?: string
  source?: 'manual' | 'decode' | 'matrix'
  source_ref?: string
  decode?: string
}

export type DecodeBody = {
  text: string
  metrics?: string
  platform?: string
  goal?: string
  profile_id?: string
}

export const topicsApi = {
  list: (opts: { profile_id?: string; status?: TopicStatus; q?: string } = {}) =>
    api.get<TopicsResponse>(`/topics${qs(opts)}`),

  create: (body: CreateTopicBody) => api.post<Topic>('/topics', body, { headers: JSON_HEADERS }),

  detail: (id: string) =>
    api.get<{ topic: Topic; score: Omit<TopicScore, 'title'> | null }>(`/topics/${id}`),  update: (id: string, changes: { title?: string; angle?: string; status?: TopicStatus }) =>
    api.patch<Topic>(`/topics/${id}`, changes, { headers: JSON_HEADERS }),

  remove: (id: string) =>
    api.del<{ ok: boolean; id: string }>(`/topics/${id}`, { headers: JSON_HEADERS }),

  decode: (body: DecodeBody) =>
    api.post<DecodeResult>('/topics/decode', body, { headers: JSON_HEADERS }),

  score: (topic_id: string, profile_id?: string) =>
    api.post<ScoreResult>('/topics/score', { topic_id, profile_id }, { headers: JSON_HEADERS }),

  matrix: (body: { pillars: string[]; formats: string[]; per_combo?: number; profile_id?: string }) =>
    api.post<MatrixResult>('/topics/matrix', body, { headers: JSON_HEADERS }),

  hooks: (body: { topic_id?: string; title?: string; platform?: string; profile_id?: string }) =>
    api.post<HooksResult>('/topics/hooks', body, { headers: JSON_HEADERS }),
}
