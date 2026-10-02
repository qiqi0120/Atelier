/** SPEC-12 · 发现域类型（与后端 api/discovery.py 的响应形状一一对应）。 */

/** F-D5 订阅 */
export type Subscription = {
  id: string
  name: string
  platform: string
  kind: 'blogger' | 'media' | 'newsletter'
  source: 'rss' | 'manual'
  url: string
  keywords: string[]
  notes: string
  enabled: boolean
  last_fetched_at: string
  created_at: string
  updated_at: string
}

export type SubscriptionInput = {
  name: string
  kind: Subscription['kind']
  source: Subscription['source']
  url?: string
  platform?: string
  keywords?: string
  notes?: string
}

/** F-D7 feed 条目（列表带 subscription_name） */
export type FeedItem = {
  id: string
  subscription_id: string
  subscription_name: string
  title: string
  url: string
  summary: string
  published_at: string
  fetched_at: string
  dedup_key: string
}

/** 热点素材 */
export type HotEntry = {
  id: string
  title: string
  source: 'rss' | 'manual'
  platform: string
  url: string
  heat: string
  note: string
  entry_date: string
  status: 'pending' | 'digested' | 'archived'
  digest_id: string
  created_at: string
  updated_at: string
}

export type HotListResponse = {
  items: HotEntry[]
  total: number
  counts: Record<HotEntry['status'], number>
}

export type HotInput = {
  title: string
  platform?: string
  url?: string
  heat?: string
  note?: string
  entry_date?: string
}

/** F-D8 日报 */
export type HotDigest = {
  id: string
  title: string
  window_start: string
  window_end: string
  markdown: string
  entry_ids: string[]
  created_at: string
}

export type DigestResult = {
  insufficient: false
  digest: HotDigest
  markdown: string
  sections: Record<string, boolean>
  entry_count: number
  gate_report: import('@/lib/gates').GateReportT
}

/** 诚实模式：素材池为空不调模型（SPEC-12 §0 D3） */
export type DigestInsufficient = {
  insufficient: true
  need: number
  stats: Record<string, number>
  message: string
}

export type DigestResponse = DigestResult | DigestInsufficient

/** F-D11 内容缺口 */
export type GapItem = { direction: string; demand: string; evidence: string; action: string }

export type GapsStats = {
  window_days: number
  feed_total: number
  keyword_counts: Record<string, number>
  bigram_counts: Record<string, number>
  topic_titles: string[]
  draft_titles: string[]
  my_counts: Record<string, number>
}

export type GapsResult = {
  insufficient: false
  gaps: GapItem[]
  stats: GapsStats
  notice: string
  gate_report: import('@/lib/gates').GateReportT
}

export type GapsInsufficient = {
  insufficient: true
  need: number
  stats: GapsStats
  message: string
}

export type GapsResponse = GapsResult | GapsInsufficient

/** F-D12 算法追踪（手工时间线） */
export type AlgorithmNote = {
  id: string
  platform: string
  noted_at: string
  change: string
  impact: string
  source: string
  created_at: string
  updated_at: string
}

export const HOT_STATUS_LABEL: Record<HotEntry['status'], string> = {
  pending: '待处理',
  digested: '已进日报',
  archived: '已归档',
}

export const HOT_STATUS_TONE: Record<HotEntry['status'], 'warn' | 'accent' | 'neutral'> = {
  pending: 'warn',
  digested: 'accent',
  archived: 'neutral',
}

export const SUB_KIND_LABEL: Record<Subscription['kind'], string> = {
  blogger: '博主',
  media: '媒体',
  newsletter: 'Newsletter',
}
