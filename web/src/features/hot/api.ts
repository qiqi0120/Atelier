/** SPEC-12 §2 · 发现域 API client（唯一出口，只做 URL 拼装与类型标注）。 */

import { api } from '@/lib/api'
import type {
  AlgorithmNote,
  DigestResponse,
  FeedItem,
  GapsResponse,
  HotDigest,
  HotEntry,
  HotInput,
  HotListResponse,
  Subscription,
  SubscriptionInput,
} from './types'

/** 写请求必须显式带 Content-Type：地基的跨站写中间件（SPEC-01 §8）要求。 */
const JSON_HEADERS = { 'Content-Type': 'application/json' } as const

function qs(params: Record<string, string | number | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
  return parts.length ? `?${parts.join('&')}` : ''
}

export const discoveryApi = {
  // ---- 订阅 ----
  listSubscriptions: (kind = '', source = '') =>
    api.get<{ items: Subscription[]; total: number }>(
      `/discovery/subscriptions${qs({ kind, source })}`,
    ),
  createSubscription: (body: SubscriptionInput) =>
    api.post<Subscription>('/discovery/subscriptions', body, { headers: JSON_HEADERS }),
  updateSubscription: (id: string, patch: Partial<SubscriptionInput> & { enabled?: boolean }) =>
    api.patch<Subscription>(`/discovery/subscriptions/${id}`, patch, { headers: JSON_HEADERS }),
  deleteSubscription: (id: string) =>
    api.del<{ ok: boolean }>(`/discovery/subscriptions/${id}`, { headers: JSON_HEADERS }),
  fetchSubscription: (id: string) =>
    api.post<{ parsed: number; filtered: number; inserted: number }>(
      `/discovery/subscriptions/${id}/fetch`,
      {},
      { headers: JSON_HEADERS },
    ),
  fetchAll: () =>
    api.post<{
      results: { ok: boolean; name: string; inserted?: number; error?: string }[]
      total: number
      ok_count: number
      inserted: number
    }>('/discovery/fetch-all', {}, { headers: JSON_HEADERS }),
  ingestManual: (id: string, body: { title: string; url?: string; summary?: string; published_at?: string }) =>
    api.post<{ inserted: boolean }>(`/discovery/subscriptions/${id}/ingest`, body, {
      headers: JSON_HEADERS,
    }),

  // ---- feed / UGC ----
  feed: (params: { subscription_id?: string; q?: string; days?: number; limit?: number }) =>
    api.get<{ items: FeedItem[]; total: number; days: number }>(`/discovery/feed${qs(params)}`),
  ugc: (q: string) =>
    api.get<{ q: string; items: FeedItem[]; total: number; notice: string }>(
      `/discovery/ugc${qs({ q })}`,
    ),

  // ---- 热点素材池 / 日报 ----
  hot: (status = '') => api.get<HotListResponse>(`/discovery/hot${qs({ status })}`),
  createHot: (body: HotInput) =>
    api.post<HotEntry>('/discovery/hot', body, { headers: JSON_HEADERS }),
  archiveHot: (id: string, status: HotEntry['status']) =>
    api.patch<HotEntry>(`/discovery/hot/${id}`, { status }, { headers: JSON_HEADERS }),
  hotFromFeed: (ids: string[]) =>
    api.post<{ inserted: number; skipped: string[]; created: { id: string }[] }>(
      '/discovery/hot/from-feed',
      { ids },
      { headers: JSON_HEADERS },
    ),
  digest: (profile_id?: string) =>
    api.post<DigestResponse>('/discovery/hot/digest', { profile_id }, { headers: JSON_HEADERS }),
  digests: () => api.get<{ items: HotDigest[]; total: number }>('/discovery/hot/digests'),

  // ---- 算法追踪 / 内容缺口 ----
  algorithmNotes: (platform = '') =>
    api.get<{ items: AlgorithmNote[]; total: number; notice: string }>(
      `/discovery/algorithm-notes${qs({ platform })}`,
    ),
  createAlgorithmNote: (body: {
    platform: string
    noted_at: string
    change: string
    impact?: string
    source?: string
  }) => api.post<AlgorithmNote>('/discovery/algorithm-notes', body, { headers: JSON_HEADERS }),
  deleteAlgorithmNote: (id: string) =>
    api.del<{ ok: boolean }>(`/discovery/algorithm-notes/${id}`, { headers: JSON_HEADERS }),
  gaps: (profile_id?: string) =>
    api.post<GapsResponse>('/discovery/gaps', { profile_id }, { headers: JSON_HEADERS }),
}
