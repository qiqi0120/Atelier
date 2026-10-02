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
