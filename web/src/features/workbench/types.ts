/** SPEC-15 §2 · 工作台/看板数据契约（后端 /api/attribution/*，全部真实录入或现查）。 */

/** 今日待办条目：kind 决定 Chip 文案，to 是站内跳转路径 */
export type TodoItem = {
  kind: 'draft' | 'topic' | 'calendar' | 'hot'
  title: string
  to: string
}

export type SchedulerStatus = {
  enabled: boolean
  interval_seconds: number
  due_count: number
  last_tick: string
  running: boolean
  now: string
  notice: string
}

/** F-H1 工作台概览：全部 SQL 现查，不许写死数字 */
export type WorkbenchSummary = {
  topics: { todo: number; doing: number; done: number }
  drafts_pending: number
  calendar_today: number
  hot_pending: number
  artifacts_last_7d: number
  records_last_7d: { sent: number; failed: number }
  scheduler: SchedulerStatus
  todo_items: TodoItem[]
  as_of: string
}

export type SnapshotPoint = { captured_at: string; followers: number }

export type MetricsDayPoint = {
  collected_at: string
  views: number
  likes: number
  comments: number
  shares: number
}

export type TopContent = {
  title: string
  platform: string
  views: number
  likes: number
}

/** F-H2 数据看板：无快照且无表现 → insufficient（看板只画真实录入的数据） */
export type DashboardResponse = {
  platform: string
  days: number
  snapshots: SnapshotPoint[]
  metrics_by_day: MetricsDayPoint[]
  top_contents: TopContent[]
  insufficient: boolean
  message?: string
}
