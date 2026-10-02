/* =============================================================================
   Atelier · 前端类型（对齐 SPEC-01 §6 core/models.py，字段名冻结）
   注意：后端模型名与字段在 M0+M1 期间不可变；改这里必须先改 spec。
   ========================================================================== */

/* ---------- 画像 ---------- */
export type Profile = {
  id: string
  name: string
  platforms: string[]
  identity: string
  style: string
  audience: string
  platform_rules: string
  preferences: string
  memories: Memory[]
  general_mode: boolean
  created_at: string
  updated_at: string
}

export type Memory = {
  id: string
  text: string
  source: '归因' | '手动' | '对话内记下' | string
  created_at: string
  adopted: boolean
}

/* ---------- 会话 ---------- */
export type Session = {
  id: string
  title: string
  profile_id: string | null
  created_at: string
  updated_at: string
  archived: boolean
  last_turn_id: string | null
}

export type MessageRole = 'user' | 'assistant' | 'system'

export type Message = {
  id: string
  session_id: string
  role: MessageRole
  text: string
  turn_id: string | null
  attachments: Attachment[]
  gate_report: GateReport | null
  created_at: string
}

export type AttachmentKind = 'image' | 'video' | 'audio' | 'doc'

export type Attachment = {
  id: string
  kind: AttachmentKind
  /** 相对 outputs/ 的路径 */
  path: string
  name: string
  size: number
  mime: string
}

/* ---------- 对话流（SPEC-01 §3） ---------- */
export type EventType =
  | 'thinking_start'
  | 'thinking_delta'
  | 'text_delta'
  | 'tool_call'
  | 'tool_result'
  | 'question'
  | 'artifact'
  | 'gate_result'
  | 'done'
  | 'error'

export type TurnEvent = {
  type: EventType
  turn_id: string
  data: Record<string, unknown>
}

/* ---------- 门禁（SPEC-01 §5） ---------- */
export type Severity = 'block' | 'warn'

export type GateItem = {
  gate: string
  label: string
  severity: Severity
  passed: boolean
  actual: number | string | null
  limit: number | string | null
  message: string
  fix_hint: string | null
}

export type GateReport = {
  items: GateItem[]
  blocked?: boolean
}

/* ---------- 技能 / 能力 ---------- */
export type SkillLayer = '发现' | '策划' | '制作' | '发布' | '归因' | '通用'

/** v0 已验证 / v1 可用 / v2 需配置 / v3 接入中（UI-SPEC 规则 2） */
export type Maturity = 'v0' | 'v1' | 'v2' | 'v3'

export const MATURITY_LABEL: Record<Maturity, string> = {
  v0: '已验证',
  v1: '可用',
  v2: '需配置',
  v3: '接入中',
}

export type SkillParam = {
  key: string
  label: string
  default: string
}

export type SkillMeta = {
  id: string
  name: string
  layer: SkillLayer
  maturity: Maturity
  /** F-C2 触发语 */
  trigger: string
  /** 「本地 · 免费」/「按量计费 · 需密钥」 */
  cost: string
  required_keys: string[]
  params: SkillParam[]
  body_markdown: string
  script: string | null
}

export type Capability = {
  id: string
  group: string
  name: string
  trigger: string
  maturity: Maturity
  skill_id: string | null
}

/* ---------- 发布 ---------- */
export type PlatformKey = 'xhs' | 'dy' | 'gzh'

export type PublishStatus = 'pending' | 'adapting' | 'ready' | 'publishing' | 'sent' | 'failed'

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

/* ---------- 错误（SPEC-01 §2） ---------- */
export type ErrorCode =
  | 'PathEscapeError'
  | 'ValidationError'
  | 'NotFound'
  | 'ProfileNotFound'
  | 'SessionBusy'
  | 'HarnessError'
  | 'HarnessAuthError'
  | 'HarnessTimeout'
  | 'GateBlocked'
  | 'SkillMissingKey'
  | 'SkillNotFound'
  | 'SkillRunFailed'
  | 'PlatformAuthExpired'
  | 'PlatformSmsWall'
  | 'PublishFailed'
  | 'SystemFileProtected'
  | 'SnapshotStale'

export type ApiErrorBody = {
  error: {
    code: ErrorCode | string
    message: string
    detail?: unknown
    hint?: string
  }
}

/* ---------- 内容库 / 账号 ---------- */
export type LibraryNode = {
  name: string
  kind: 'project' | 'zone' | 'file'
  count?: number
  is_system?: boolean
  rel_path?: string
  size?: number
  mime?: string
}

export type PlatformCred = {
  id: string
  platform: string
  account: string | null
  state: 'unknown' | 'valid' | 'expired'
  verified_at: string | null
  created_at: string
}

export type HealthReport = {
  ok: boolean
  checks: { id: string; label: string; passed: boolean; detail: string }[]
}
