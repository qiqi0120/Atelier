/** SPEC-08 · 选题域类型（与后端 api/topics.py 的响应形状一一对应）。
 *
 * 门禁报告形状是 API 契约的一部分，归 lib/gates.ts（SPEC-09 起，日历域同用）。
 */

import type { GateReportT } from '@/lib/gates'

export type { GateItemT, GateReportT } from '@/lib/gates'

export type TopicStatus = 'todo' | 'doing' | 'done'
/** calendar 由 SPEC-09（日历建议）落池；hot 留给 M2-3 */
export type TopicSource = 'manual' | 'decode' | 'matrix' | 'calendar' | 'hot'
export type Verdict = 'do' | 'pivot' | 'dont'

export type Topic = {
  id: string
  profile_id: string | null
  title: string
  angle: string
  source: TopicSource
  source_ref: string
  status: TopicStatus
  decode: string
  /** 建议发布日期（YYYY-MM-DD），空串 = 未排期（SPEC-09） */
  due_date: string
  created_at: string
  updated_at: string
}

export type TopicDims = {
  traffic: number
  match: number
  differentiation: number
  timing: number
  monetization: number
  cost: number
  risk: number
}

export type TopicScore = {
  id: string
  topic_id: string
  dims: TopicDims
  total: number
  verdict: Verdict
  reason: string
  created_at: string
}

export type DecodeResult = {
  decode_markdown: string
  sections: Record<string, boolean>
  gate_report: GateReportT
  topic_seed: { title: string; angle: string }
}

export type ScoreResult = {
  id: string
  topic_id: string
  title: string
  dims: TopicDims
  total: number
  verdict: Verdict
  reason: string
  created_at: string
}

export type MatrixResult = { items: Topic[]; count: number; gate_report: GateReportT }

export type HookVariant = { text: string; chars: number; limit: number; passed: boolean }
export type HooksResult = { variants: HookVariant[]; gate_report: GateReportT }

export type TopicsResponse = { items: Topic[]; total: number }

/** 看板三列的展示元数据（顺序即流转顺序，todo → doing → done） */
export const STATUS_FLOW: TopicStatus[] = ['todo', 'doing', 'done']

export const STATUS_LABEL: Record<TopicStatus, string> = {
  todo: '待做',
  doing: '进行中',
  done: '已完成',
}

export const SOURCE_LABEL: Record<TopicSource, string> = {
  manual: '手动',
  decode: '拆解',
  matrix: '矩阵',
  calendar: '日历',
  hot: '热点',
}

export const VERDICT_META: Record<Verdict, { label: string; hint: string }> = {
  do: { label: '建议做', hint: '总分高，值得投入' },
  pivot: { label: '改方向', hint: '中间分数，调整角度再做' },
  dont: { label: '不做', hint: '总分偏低，放弃或重开' },
}

/** 评分 7 维的展示序与中文标签（SPEC-08 §3） */
export const DIM_ROWS: { key: keyof TopicDims; label: string }[] = [
  { key: 'traffic', label: '流量潜力' },
  { key: 'match', label: '账号匹配' },
  { key: 'differentiation', label: '竞争差异化' },
  { key: 'timing', label: '时效' },
  { key: 'monetization', label: '变现' },
  { key: 'cost', label: '成本' },
  { key: 'risk', label: '风险' },
]
