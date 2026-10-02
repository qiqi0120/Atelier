/** SPEC-04 §5 · 技能库域 API client（唯一出口，只做 URL 拼装与类型标注）。 */

import { api } from '@/lib/api'
import type { KeysResponse, SkillDetail, SkillListResponse, SkillRun, SkillRunResponse } from '@/lib/types'

/** 写请求必须显式带 Content-Type：地基的跨站写中间件（SPEC-01 §8）要求。 */
const JSON_HEADERS = { 'Content-Type': 'application/json' } as const

export type SkillRunInput = {
  params: Record<string, string>
  /** 默认项目；运行记录落库用 */
  project?: string
  profile_id?: string
  /** 付费技能：首次运行返回费用预估，确认后带 true 重发（PRD 原则三） */
  confirm_cost?: boolean
  /** true = 同步等结果；默认异步 + 轮询 stream_url */
  wait?: boolean
}

export const skillsApi = {
  /** 列表不含 body_markdown；?layer= 按层过滤 */
  list: (layer?: string) =>
    api.get<SkillListResponse>(`/skills${layer ? `?layer=${encodeURIComponent(layer)}` : ''}`),
  /** 详情 = brief + SKILL.md 全文 + block_reason（缺钥时的禁用原因） */
  detail: (id: string) => api.get<SkillDetail>(`/skills/${encodeURIComponent(id)}`),
  /** 就地运行。缺密钥 → 409 SkillMissingKey；付费未确认 → cost_pending */
  run: (id: string, body: SkillRunInput) =>
    api.post<SkillRunResponse>(`/skills/${encodeURIComponent(id)}/run`, body, { headers: JSON_HEADERS }),
  /** 单次运行状态（status=running 时轮询它） */
  runStatus: (runId: string) => api.get<SkillRun>(`/skills/runs/${encodeURIComponent(runId)}`),
  /** 运行历史（倒序），抽屉里取最近 5 条 */
  history: (skillId: string, limit = 5) =>
    api.get<{ runs: SkillRun[] }>(`/skills/runs?skill_id=${encodeURIComponent(skillId)}&limit=${limit}`),
  /** 掩码列表（永不回传明文） */
  keys: () => api.get<KeysResponse>('/keys'),
  /** 写密钥；留空不提交由前端保证（后端对空值原样返回 unchanged） */
  saveKey: (keyName: string, value: string) =>
    api.post<{ ok: boolean; unchanged?: boolean; masked?: string }>(
      '/keys',
      { key_name: keyName, value },
      { headers: JSON_HEADERS },
    ),
}
