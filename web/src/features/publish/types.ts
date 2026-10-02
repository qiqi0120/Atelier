/** =============================================================================
   发布中心 · 共享类型与 API 封装（SPEC-06）
   ★ 字数读数一律来自后端（SPEC-06 §2），**前端不重复实现计数逻辑**。
   ========================================================================== */

import { api, request } from '@/lib/api'

export type PlatformKey = 'xhs' | 'dy' | 'gzh'
export type PublishStatus = 'pending' | 'adapting' | 'ready' | 'publishing' | 'sent' | 'failed'
export type Severity = 'block' | 'warn'

export type AuthState = {
  platform: string
  logged_in: boolean
  account: string | null
  need_sms: boolean
  message: string
  verified_at: string | null
}

export type PlatformMeta = {
  platform: PlatformKey
  name: string
  forms: string[]
  form_label: string
  title_max: number
  body_max: number
  needs_cover: boolean
  cover_ratio: string | null
  constraint: string
  auth: AuthState
}

export type PlatformVariant = {
  platform: PlatformKey
  title: string
  body: string
  char_count: number
  char_limit: number
  over_limit: boolean
  adapted: boolean
  status: PublishStatus
  error: string | null
  published_url: string | null
}

export type PublishDraft = {
  id: string
  project: string | null
  title: string
  body: string
  topic_tags: string[]
  variants: PlatformVariant[]
  attachments: string[]
  /** 关联选题（可空，SPEC-10） */
  topic_id: string | null
  /** 计划发布日 YYYY-MM-DD（可空；人工排期上日历，非平台定时发送） */
  scheduled_date: string | null
  created_at: string
  updated_at: string
}

export type PrecheckItem = {
  id: string
  label: string
  severity: Severity
  passed: boolean
  message: string
  fix_hint: string | null
  platform: string | null
}

export type PrecheckResult = {
  items: PrecheckItem[]
  blocked: boolean
  block_count: number
  warn_count: number
}

/** 单平台一次发布的结果。★ ``dry_run`` 必须原样展示，不许让用户误以为真发出去了。 */
export type PlatformRun = {
  platform: PlatformKey
  name: string
  status: PublishStatus | 'awaiting_sms'
  url: string | null
  error: string | null
  error_code: string | null
  hint: string | null
  record_id: string | null
  dry_run: boolean
  raw: Record<string, unknown>
}

export type PublishResult = {
  results: PlatformRun[]
  dry_run: boolean
  notice: string
  ok_count: number
  failed_count: number
  draft?: PublishDraft
}

/** 适配流事件（SSE）。``delta`` 逐字、``variant`` 成品、``error`` 单平台失败。 */
export type AdaptEvent = {
  type: 'thinking' | 'delta' | 'variant' | 'error' | 'summary'
  platform?: PlatformKey
  text?: string
  acc?: string
  message?: string
  variant?: PlatformVariant
  ok?: PlatformKey[]
  failed?: Record<string, string>
}

export type PublishRecord = {
  id: string
  draft_id: string
  platform: PlatformKey
  platform_name: string
  status: string
  title: string | null
  error: string | null
  error_code: string | null
  hint: string | null
  published_url: string | null
  created_at: string
  dry_run: boolean
}

/* ------------------------------------------------------------------ 端点 */

export const publishApi = {
  platforms: () => api.get<{ platforms: PlatformMeta[] }>('/publish/platforms'),

  listDrafts: () => api.get<{ drafts: PublishDraft[] }>('/publish/drafts'),

  createDraft: (body: { title?: string; body?: string; topic_tags?: string[] }) =>
    api.post<PublishDraft>('/publish/drafts', body),

  getDraft: (id: string) => api.get<PublishDraft>(`/publish/drafts/${id}`),

  /** 草稿自动保存：前端 debounce 800ms 打这个接口（SPEC-06 §6） */
  patchDraft: (id: string, patch: Partial<PublishDraft>) =>
    request<PublishDraft>(`/publish/drafts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
      silent: true,
    }),

  /** 适配走 SSE：逐字回调（F-G10 前端逐字渲染） */
  adapt: async (id: string, platforms: PlatformKey[], onEvent: (e: AdaptEvent) => void) => {
    const res = await fetch(`/api/publish/drafts/${id}/adapt`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platforms }),
    })
    if (!res.ok || !res.body) {
      throw new Error(`适配请求失败（HTTP ${res.status}）`)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const parts = buf.split('\n\n')
      buf = parts.pop() ?? ''
      for (const part of parts) {
        for (const line of part.split('\n')) {
          if (!line.startsWith('data: ')) continue
          try {
            onEvent(JSON.parse(line.slice(6)) as AdaptEvent)
          } catch {
            /* 半包/坏行跳过，不让一条坏事件打断整条流 */
          }
        }
      }
    }
  },

  precheck: (id: string, platforms?: PlatformKey[]) =>
    api.post<PrecheckResult>(`/publish/drafts/${id}/precheck`, { platforms: platforms ?? [] }),

  autofix: (id: string, platform: PlatformKey, field: 'body' | 'title' | 'all') =>
    api.post<{
      ok: boolean
      before: number
      after: number
      limit: number
      changes: Record<string, { before: number; after: number; limit: number }>
      variant: PlatformVariant
      draft: PublishDraft
    }>(
      `/publish/drafts/${id}/autofix`,
      { platform, field },
    ),

  publish: (id: string, platforms: PlatformKey[]) =>
    api.post<PublishResult>(`/publish/drafts/${id}/publish`, { confirm: true, platforms, dry_run: true }),

  retry: (recordId: string) =>
    api.post<PublishResult & { skipped?: boolean; message?: string }>(`/publish/records/${recordId}/retry`, {}),

  records: (id: string) => api.get<{ records: PublishRecord[] }>(`/publish/drafts/${id}/records`),

  smsState: (recordId: string) =>
    api.get<{ need_sms: boolean; expires_in: number; message: string }>(`/publish/sms/${recordId}`),

  submitSms: (recordId: string, code: string) =>
    api.post<{ accepted: boolean; notice: string }>(`/publish/sms/${recordId}`, { code }),
}

/** 预检项 → 前端上色（UI-SPEC 规则 17：硬门禁红 / 软提醒琥珀 / 通过绿） */
export function checkTone(item: PrecheckItem): 'ok' | 'w' | 'd' {
  if (item.passed) return 'ok'
  return item.severity === 'block' ? 'd' : 'w'
}
