/** SPEC-05 §3 · 内容库 API 的 TS 形状。与后端 service.py 的返回体一一对应。 */

export type LibKind = 'image' | 'video' | 'audio' | 'doc' | 'file'

export type LibZone = '成品' | '素材' | '.session'

export interface LibProject {
  name: string
  path: string
  rel_to_root: string
  product_count: number
  material_count: number
  system_count: number
  file_count: number
  total_bytes: number
  total_size_human: string
  updated_at: string | null
}

export interface LibDir {
  name: string
  path: string
  rel_to_root: string
  kind: 'dir'
  is_system: boolean
}

export interface LibFile {
  name: string
  /** 相对 outputs/ 的 posix 路径，喂给 /library/stream?path= */
  path: string
  rel_to_root: string
  zone: string
  kind: LibKind
  ext: string
  mime: string
  size: number
  size_human: string
  width: number | null
  height: number | null
  duration: number | null
  duration_human: string | null
  modified_at: string | null
  is_system: boolean
  previewable: boolean
  download_url: string
}

export interface LibCrumb {
  label: string
  project: string
  zone: string
  sub: string
  path: string
  is_system?: boolean
}

export interface TreeResponse {
  project: string
  zone: string
  sub: string
  path: string
  rel_to_root: string
  breadcrumb: LibCrumb[]
  dirs: LibDir[]
  files: LibFile[]
  count: number
  is_system: boolean
  /** 本次扫描剔除的孤儿索引条数（文件被手动删了 → 索引自动修正，不静默） */
  orphan_removed: number
}

export interface FilesResponse {
  project: string
  zone: string
  sub: string
  kind: string
  q: string
  files: LibFile[]
  count: number
  counts_by_kind: Record<string, number>
  orphan_removed: number
}

export interface ProjectsResponse {
  projects: LibProject[]
  count: number
  root: string
  zones: string[]
}

export interface PreviewResponse {
  path: string
  name: string
  format: 'markdown' | 'html' | 'json' | 'text'
  content: string
  truncated: boolean
  size_human: string
  hint: string | null
  is_system: boolean
}

/** 破坏性操作前置口令：`warning` 已在后端拼好，**前后端说的是同一句话**。 */
export interface ConfirmToken {
  token: string
  expires_in: number
  target: string
  warning: string
  requires_typing: string | null
  name?: string
  size?: number
  size_human?: string
  file_count?: number
  total_bytes?: number
  total_size_human?: string
}

export interface DeleteResult {
  ok: boolean
  statement: string
  deleted?: string
  name?: string
  file_count?: number
  total_size_human?: string
}
