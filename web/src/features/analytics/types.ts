/** SPEC-11 · 分析域类型（与后端 api/analytics.py 的响应形状一一对应）。 */

import type { GateReportT } from '@/lib/gates'

/** F-E14 受众画像卡 */
export type InsightCard = {
  persona: string
  pains: string[]
  scenarios: string[]
  preferences: string[]
  notes: string[]
}

/** F-D10 竞品分析：三列表 */
export type CompetitorResult = {
  topics: string[]
  formats: string[]
  patterns: string[]
  gate_report: GateReportT
}

/** F-E12 内容策略：4 段 markdown */
export type StrategyResult = {
  markdown: string
  sections: Record<string, boolean>
  gate_report: GateReportT
}

export type AudienceResult = { card: InsightCard; gate_report: GateReportT }

/** F-E13 账号诊断 */
export type DiagnoseFinding = { dimension: string; status: 'good' | 'warn' | 'bad'; note: string }

export type DiagnoseStats = {
  records_total: number
  records_last_30d: number
  records_failed: number
  by_platform: Record<string, number>
  drafts_total: number
  topics_flow: Record<'todo' | 'doing' | 'done', number>
  recent_titles: string[]
}

export type DiagnoseResult = {
  insufficient: false
  stats: DiagnoseStats
  findings: DiagnoseFinding[]
  advice: string[]
  notice: string
  gate_report: GateReportT
}

/** 诚实模式：发布记录不足时后端不调模型、不给分数（SPEC-11 §0 D3） */
export type DiagnoseInsufficient = {
  insufficient: true
  stats: DiagnoseStats
  need: number
  message: string
}

export type DiagnoseResponse = DiagnoseResult | DiagnoseInsufficient

export const FINDING_TONE: Record<DiagnoseFinding['status'], 'accent' | 'warn' | 'danger'> = {
  good: 'accent',
  warn: 'warn',
  bad: 'danger',
}

export const FINDING_LABEL: Record<DiagnoseFinding['status'], string> = {
  good: '良好',
  warn: '待改进',
  bad: '需行动',
}

// -------------------------------------------------------------------------
// M5 · 数据录入（SPEC-15：平台数据不可抓取，三张表全部手工抄录）
// -------------------------------------------------------------------------

/** 录入表单共用的平台清单（与看板 Select 同一口径） */
export const ENTRY_PLATFORMS = ['xhs', 'dy', 'gzh', 'ks', 'zhihu', 'bilibili', 'wcs'] as const

/** F-G29 账号快照（后端行形状） */
export type Snapshot = {
  id: string
  platform: string
  captured_at: string
  followers: number
  likes_total: number
  works_total: number
  note: string
  created_at: string
  updated_at: string
}

export type SnapshotInput = {
  platform: string
  captured_at?: string
  followers?: number
  likes_total?: number
  works_total?: number
  note?: string
}

/** F-G31 内容表现（后端行形状） */
export type Metric = {
  id: string
  record_id: string
  platform: string
  views: number
  likes: number
  comments: number
  shares: number
  collected_at: string
  note: string
  created_at: string
  updated_at: string
}

export type MetricInput = {
  record_id: string
  platform: string
  views?: number
  likes?: number
  comments?: number
  shares?: number
  collected_at?: string
  note?: string
}

/** 表现录入下拉数据源：最近 20 条发布记录（左联草稿取标题） */
export type RecentRecord = {
  id: string
  platform: string
  title: string
  created_at: string
  draft_title: string
}

/** F-G34 投入台账（后端行形状） */
export type RoiEntry = {
  id: string
  record_id: string
  project: string
  hours: number
  amount: number
  note: string
  created_at: string
}

export type RoiInput = {
  record_id?: string
  project?: string
  hours: number
  amount: number
  note?: string
}

/** ROI 汇总：无投入记录 → insufficient（不编产出比） */
export type RoiSummary = {
  insufficient: boolean
  need?: number
  message?: string
  days?: number
  total_hours?: number
  total_amount?: number
  content_count?: number
  output?: { total_views: number; total_likes: number; total_comments: number; total_shares: number }
  roi_hint?: string
}
