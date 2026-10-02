/** SPEC-15 §2 · 工作台域 API client（唯一出口，只做 URL 拼装与类型标注）。
 *
 * 数据源是归因域的只读端点：工作台概览（F-H1）与创作数据看板（F-H2）。
 */

import { api } from '@/lib/api'
import type { DashboardResponse, WorkbenchSummary } from './types'

function qs(params: Record<string, string | number | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
  return parts.length ? `?${parts.join('&')}` : ''
}

export const workbenchApi = {
  /** F-H1 概览（scheduler 口径来自 publish.scheduler.get_status()） */
  summary: () => api.get<WorkbenchSummary>('/attribution/workbench-summary'),

  /** F-H2 看板（insufficient 时调用方自渲染空态；handled 避免与静态错误条双报） */
  dashboard: (platform = '', days = 30, opts?: { handled?: boolean }) =>
    api.get<DashboardResponse>(`/attribution/dashboard${qs({ platform, days })}`, opts),
}
