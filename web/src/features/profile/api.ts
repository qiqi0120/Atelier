/* =============================================================================
   账号画像域 · API client（SPEC-02 §5 的 13 个端点）
   - 字段名与后端 core/models.py 严格对齐（SPEC-01 §6 冻结）
   - 写请求统一走 lib/api 的 ApiError + 自动 toast
   ========================================================================== */

import { api, request } from '@/lib/api'
import type { Memory, Profile } from '@/lib/types'

/** 列表页摘要：后端 wizard_marker() 的形状 */
export type ProfileBrief = {
  id: string
  name: string
  platforms: string[]
  general_mode: boolean
  /** 六维各 0–100 */
  completeness: Record<string, number>
  /** 六维均值，前端 tab 上显示的那个百分比 */
  completeness_overall: number
  memory_count: number
  updated_at: string
  created_at: string
}

export type ProfileDetail = Profile & {
  completeness: Record<string, number>
  completeness_overall: number
  dimension_labels: Record<string, string>
  md_path: string
}

export type WizardStepMeta = {
  key: string
  index: number
  title: string
  sub: string
  fields: string[]
  skippable: boolean
  hint: string
}

export type WizardProgress = {
  token: string
  profile_id: string
  completed: number
  progress: number
  progress_label: string
  next_step: string
  skipped: string[]
  finished: boolean
  profile?: ProfileDetail
}

export type CreateProfileResult = ProfileDetail & {
  wizard_token: string
  wizard: { token: string; steps: WizardStepMeta[]; next_step: string; progress: number; progress_label: string }
}

export type PreviewResult = {
  profile_id: string
  system_prompt: string
  prefix: string
  base: string
  suffix: string
  general_mode: boolean
  injected: boolean
  reason: string
  /** 通用模式下这里必须为空数组——验收 3 的机器判定 */
  leaked_dims: string[]
  prefix_chars: number
}

/** 六维 key（顺序 = 原型左导航顺序，memories 在最后） */
export const DIM_KEYS = [
  'identity',
  'style',
  'audience',
  'platform_rules',
  'preferences',
  'memories',
] as const

export type DimKey = (typeof DIM_KEYS)[number]

/** 左导航用中文名（与后端 DIMENSION_LABELS 一致，这里只做兜底展示） */
export const DIM_NAMES: Record<DimKey, string> = {
  identity: '定位',
  style: '风格',
  audience: '受众',
  platform_rules: '平台',
  preferences: '偏好红线',
  memories: '长期记忆',
}

/** 每个维度的编辑提示（原型 dimHint 的文案） */
export const DIM_HINTS: Record<DimKey, string> = {
  identity: '建议 100–300 字，写清楚「你到底是谁」',
  style: '建议 100–300 字，句子长短、结论位置、能不能用口头禅',
  audience: '建议 100–300 字，写给谁、他们卡在哪',
  platform_rules: '建议 100–300 字：形态、字数上限、封面比例、禁区',
  preferences: '建议 100–300 字：不想出现的话、禁忌话题、绝不做的选题',
  memories: '归因结论自动沉淀到这里，也可以在对话里说「记住这个偏好」',
}

/** 五个可编辑文本维度（memories 走独立的记忆面板，不在这里编辑） */
export const TEXT_DIMS: DimKey[] = ['identity', 'style', 'audience', 'platform_rules', 'preferences']

/** 无 body 的 DELETE 必须显式带 Content-Type，否则被地基层跨站写拦截挡成 403 */
const DEL = { headers: { 'Content-Type': 'application/json' } }

export const profileApi = {
  list: () => api.get<{ profiles: ProfileBrief[]; count: number }>('/profiles'),

  detail: (id: string) => api.get<ProfileDetail>(`/profiles/${id}`),

  create: (body: { name: string; platforms?: string[]; fields?: Record<string, string> }) =>
    api.post<CreateProfileResult>('/profiles', body),

  /** 局部更新任一维。只传要改的字段——后端按「显式给了才改」处理，不会清空别的维度。 */
  patch: (id: string, changes: Partial<Record<DimKey | 'name' | 'platforms' | 'general_mode', unknown>>) =>
    request<ProfileDetail>(`/profiles/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(changes),
    }),

  remove: (id: string) => api.del<{ ok: boolean }>(`/profiles/${id}?confirm=${encodeURIComponent(id)}`, DEL),

  wizardStep: (id: string, body: { step: string; data?: Record<string, unknown>; skip?: boolean; token?: string }) =>
    api.post<WizardProgress>(`/profiles/${id}/wizard/step`, body),

  wizardGet: (id: string, token: string) =>
    api.get<WizardProgress & { steps: WizardStepMeta[] }>(`/profiles/${id}/wizard?token=${encodeURIComponent(token)}`),

  wizardAbandon: (id: string, token: string) =>
    api.del<{ abandoned: boolean; profile_id: string; kept: boolean; profile?: ProfileDetail }>(
      `/profiles/${id}/wizard?token=${encodeURIComponent(token)}`,
      DEL,
    ),

  memories: (id: string) => api.get<{ memories: Memory[]; count: number }>(`/profiles/${id}/memories`),

  addMemory: (id: string, text: string, source = '手动') =>
    api.post<{ ok: boolean; memory: Memory; message: string }>(`/profiles/${id}/memories`, { text, source }),

  deleteMemory: (id: string, memoryId: string) =>
    api.del<{ ok: boolean }>(`/profiles/${id}/memories/${memoryId}`, DEL),

  generalMode: (id: string, enabled: boolean) =>
    api.post<ProfileDetail & { message: string }>(`/profiles/${id}/general-mode`, { enabled }),

  /** ★ 验证「画像真的注入了」的唯一手段（验收 3/4/5） */
  preview: (id: string) => api.get<PreviewResult>(`/profiles/${id}/preview`),
}

/** 「N 字」计数口径与原型一致：去掉所有空白 */
export function countChars(text: string): number {
  return text.replace(/\s/g, '').length
}

/** 把偏好红线正文拆成条目（`- xxx` 形式的行） */
export function parseRedlines(markdown: string): string[] {
  return markdown
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l.startsWith('- '))
    .map((l) => l.slice(2).trim())
    .filter(Boolean)
}

/** 红线条目 → 正文（保留没有列表化的自由文本段落） */
export function redlinesToMarkdown(items: string[], original: string): string {
  const prose = original
    .split('\n')
    .filter((l) => l.trim() && !l.trim().startsWith('- ') && !l.trim().startsWith('#'))
    .join('\n')
    .trim()
  return [prose, ...items.map((i) => `- ${i}`)].filter(Boolean).join('\n')
}
