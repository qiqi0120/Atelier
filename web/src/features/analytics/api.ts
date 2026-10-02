/** SPEC-11 §3 · 分析域 API client（唯一出口，只做 URL 拼装与类型标注）。 */

import { api } from '@/lib/api'
import type {
  AudienceResult,
  CompetitorResult,
  DiagnoseResponse,
  Metric,
  MetricInput,
  RecentRecord,
  RoiEntry,
  RoiInput,
  RoiSummary,
  Snapshot,
  SnapshotInput,
  StrategyResult,
} from './types'

/** 写请求必须显式带 Content-Type：地基的跨站写中间件（SPEC-01 §8）要求。 */
const JSON_HEADERS = { 'Content-Type': 'application/json' } as const

function qs(params: Record<string, string | number | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
  return parts.length ? `?${parts.join('&')}` : ''
}

export const analyticsApi = {
  competitor: (text: string, profile_id?: string) =>
    api.post<CompetitorResult>(
      '/analytics/competitor',
      { text, profile_id },
      { headers: JSON_HEADERS },
    ),

  strategy: (profile_id?: string) =>
    api.post<StrategyResult>('/analytics/strategy', { profile_id }, { headers: JSON_HEADERS }),

  audience: (profile_id?: string) =>
    api.post<AudienceResult>('/analytics/audience', { profile_id }, { headers: JSON_HEADERS }),

  diagnose: (profile_id?: string) =>
    api.post<DiagnoseResponse>('/analytics/diagnose', { profile_id }, { headers: JSON_HEADERS }),
}

/** SPEC-12 §3 · 策划域 P3 三工具（营销策划 / 直播策划 / 商单方案），不落库 */
export type PlanKind = 'campaign' | 'liveplan' | 'sponsorship'

export const analyticsPlanApi = {
  campaign: (theme: string, occasion: string, profile_id?: string) =>
    api.post<StrategyResult>(
      '/analytics/campaign',
      { theme, occasion, profile_id },
      { headers: JSON_HEADERS },
    ),
  liveplan: (topic: string, duration: string, profile_id?: string) =>
    api.post<StrategyResult>(
      '/analytics/liveplan',
      { topic, duration, profile_id },
      { headers: JSON_HEADERS },
    ),
  sponsorship: (brief: string, brand: string, profile_id?: string) =>
    api.post<StrategyResult>(
      '/analytics/sponsorship',
      { brief, brand, profile_id },
      { headers: JSON_HEADERS },
    ),
}

/** SPEC-15 §2 · M5 数据录入（账号快照 / 内容表现 / 投入台账），真实回收的第一步 */
export const attributionApi = {
  listSnapshots: (platform = '') =>
    api.get<{ items: Snapshot[]; total: number }>(`/attribution/snapshots${qs({ platform })}`),

  createSnapshot: (body: SnapshotInput) =>
    api.post<Snapshot>('/attribution/snapshots', body, { headers: JSON_HEADERS }),

  /** 表现录入下拉：最近 20 条发布记录（左联草稿取标题） */
  recordsRecent: () =>
    api.get<{ items: RecentRecord[]; total: number }>('/attribution/records-recent'),

  createMetric: (body: MetricInput) =>
    api.post<Metric>('/attribution/metrics', body, { headers: JSON_HEADERS }),

  createRoi: (body: RoiInput) =>
    api.post<RoiEntry>('/attribution/roi', body, { headers: JSON_HEADERS }),

  roiSummary: () => api.get<RoiSummary>('/attribution/roi/summary?days=30'),
}
