/** SPEC-05 §3 · 内容库 API client（唯一出口，只做 URL 拼装与类型标注）。 */

import { api } from '@/lib/api'
import type {
  ConfirmToken,
  DeleteResult,
  FilesResponse,
  PreviewResponse,
  ProjectsResponse,
  TreeResponse,
} from './types'

/**
 * 写请求必须显式带 `Content-Type: application/json`：地基的跨站写中间件
 * （SPEC-01 §8）会把无 Content-Type 的 DELETE 判成跨站写并 403。
 */
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

/** 媒体 src 统一走 /library/stream（服务端按 Range 分段，不整文件预加载）。 */
export function streamUrl(path: string, download = false): string {
  return `/api/library/stream${qs({ path, download: download ? 1 : undefined })}`
}

export const libraryApi = {
  projects: () => api.get<ProjectsResponse>('/library/projects'),

  createProject: (name: string) =>
    api.post<{ ok: boolean; name: string; created: boolean }>('/library/projects', { name }),

  tree: (project: string, zone: string, sub = '') =>
    api.get<TreeResponse>(`/library/tree${qs({ project, zone, sub })}`),

  files: (project: string, opts: { zone?: string; kind?: string; q?: string } = {}) =>
    api.get<FilesResponse>(`/library/files${qs({ project, ...opts })}`),

  meta: (path: string) =>
    api.get<FilesResponse['files'][number] & { system_notice: string | null }>(
      `/library/meta${qs({ path })}`,
    ),

  preview: (path: string) => api.get<PreviewResponse>(`/library/preview${qs({ path })}`),

  confirmToken: (target: { path: string } | { project: string }) =>
    api.post<ConfirmToken>('/library/confirm-token', target, { headers: JSON_HEADERS }),

  deleteFile: (path: string, confirm: string) =>
    api.del<DeleteResult>(`/library/file${qs({ path, confirm })}`, { headers: JSON_HEADERS }),

  deleteProject: (project: string, confirm: string) =>
    api.del<DeleteResult>(`/library/project${qs({ project, confirm })}`, { headers: JSON_HEADERS }),

  unlockSystem: (path: string, confirm: string) =>
    api.post<{ unlocked: boolean; enabled: boolean; notice: string; message: string }>(
      '/library/unlock-system',
      { path, confirm },
      { headers: JSON_HEADERS },
    ),
}
