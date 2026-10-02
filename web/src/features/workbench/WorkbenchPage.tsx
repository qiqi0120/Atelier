/** 工作台（F-H1）：概览/待办/最近产出全部来自 /api/attribution/workbench-summary 现查数据，
 * 创作数据看板（F-H2）是页内 section。热点速览与快捷入口保持原有装配。
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { LucideIcon } from 'lucide-react'
import {
  ArrowRight,
  ArrowUp,
  BarChart3,
  CalendarRange,
  Clock,
  Flame,
  Image as ImageIcon,
  MonitorPlay,
  TrendingUp,
} from 'lucide-react'
import { Button, Card, Chip, EmptyState, Skeleton, toast } from '@/components'
import type { ChipTone } from '@/components'
import { useAtelier } from '@/lib/store'
import { discoveryApi } from '@/features/hot/api'
import type { HotEntry } from '@/features/hot/types'
import { workbenchApi } from './api'
import { DashboardSection } from './DashboardSection'
import type { TodoItem, WorkbenchSummary } from './types'

/** 今日热点速览：SPEC-12 起接真实 /api/discovery/hot（待处理素材，至多 6 条） */
function useHotFeed() {
  const [items, setItems] = useState<HotEntry[] | null>(null)
  useEffect(() => {
    let alive = true
    discoveryApi
      .hot('pending')
      .then((r) => {
        if (alive) setItems(r.items.slice(0, 6))
      })
      .catch(() => {
        if (alive) setItems([]) // api 层已 toast；卡片内给空态
      })
    return () => {
      alive = false
    }
  }, [])
  return items
}

/** F-H1 概览：null=加载中；failed=true 表示请求失败（hero 如实提示，不假装是零） */
function useWorkbenchSummary(): { summary: WorkbenchSummary | null; failed: boolean } {
  const [summary, setSummary] = useState<WorkbenchSummary | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let alive = true
    workbenchApi
      .summary()
      .then((s) => {
        if (!alive) return
        setSummary(s)
        setFailed(false)
      })
      .catch(() => {
        if (!alive) return
        setSummary(null)
        setFailed(true)
      })
    return () => {
      alive = false
    }
  }, [])
  return { summary, failed }
}

const TODO_META: Record<TodoItem['kind'], { label: string; tone: ChipTone; icon: LucideIcon; sub: string }> = {
  draft: { label: '待发', tone: 'warn', icon: Clock, sub: '到发布中心处理' },
  topic: { label: '选题', tone: 'info', icon: ArrowUp, sub: '到选题库继续' },
  calendar: { label: '日程', tone: 'outline', icon: CalendarRange, sub: '到日历查看' },
  hot: { label: '热点', tone: 'danger', icon: Flame, sub: '到发现处理' },
}

function greet(): string {
  const h = new Date().getHours()
  const word = h < 6 ? '深夜好' : h < 11 ? '早上好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好'
  return `${word}，Mr Yu`
}

export function WorkbenchPage() {
  const navigate = useNavigate()
  const fillPrompt = useAtelier((s) => s.fillPrompt)
  const { summary, failed } = useWorkbenchSummary()
  const hotFeed = useHotFeed()

  const ask = (text: string) => {
    fillPrompt(text)
    navigate('/chat')
    toast('已填入输入框，确认后点发送', 'ok')
  }

  const scrollToDashboard = () => {
    document.getElementById('dashboard')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const topicsTotal = summary ? summary.topics.todo + summary.topics.doing + summary.topics.done : 0
  const heroAllZero =
    summary !== null &&
    summary.drafts_pending === 0 &&
    summary.topics.doing === 0 &&
    summary.artifacts_last_7d === 0

  return (
    <div className="view-pad stack" style={{ gap: 18 }}>
      <div className="hero">
        <div>
          <div className="row" style={{ gap: 7 }}>
            <h2>{greet()}</h2>
            <Chip tone="accent" icon={<i className="live-dot" />}>
              画像已生效
            </Chip>
          </div>
          {failed ? (
            <p>概览暂时没拉到（本地服务没在跑？）——刷新页面再试，不拿假数字凑。</p>
          ) : summary === null ? (
            <Skeleton width="72%" height={16} />
          ) : heroAllZero ? (
            <p>
              今天还没有排期——
              <a
                href="/topics"
                style={{ color: 'var(--accent-ink)', textDecoration: 'underline', cursor: 'pointer' }}
                onClick={(e) => {
                  e.preventDefault()
                  navigate('/topics')
                }}
              >
                去选题库找点事做
              </a>
            </p>
          ) : (
            <p>
              今天有 <b style={{ color: 'var(--ink)' }}>{summary.drafts_pending} 条</b>待发内容 ·{' '}
              {summary.topics.doing} 个选题进行中 ·{' '}
              <b style={{ color: 'var(--ink)' }}>{summary.artifacts_last_7d} 件</b>产物近 7 天入库
            </p>
          )}
        </div>
        <div className="hero-r">
          <Button onClick={() => navigate('/calendar')}>看排期</Button>
          <Button variant="primary" onClick={() => ask('帮我把母版标题改得更适合小红书和抖音')}>
            让 AI 帮我写今天的稿
          </Button>
        </div>
      </div>

      <div className="stat-row">
        <Card>
          <div className="kpi">
            <b>
              {summary ? (
                summary.topics.doing
              ) : (
                <Skeleton width={36} height={22} />
              )}
            </b>
            <span>进行中选题</span>
            <span className="mut2" style={{ fontSize: 'var(--fs-help)' }}>
              共 {topicsTotal} 条在库
            </span>
          </div>
        </Card>
        <Card>
          <div className="kpi">
            <b>{summary ? summary.drafts_pending : <Skeleton width={36} height={22} />}</b>
            <span>待发内容</span>
            <span className="mut2" style={{ fontSize: 'var(--fs-help)' }}>
              调度器 · {summary?.scheduler.due_count ?? 0} 条到期
            </span>
          </div>
        </Card>
        <Card>
          <div className="kpi">
            <b>{summary ? summary.calendar_today : <Skeleton width={36} height={22} />}</b>
            <span>今日日程</span>
            <span className="mut2" style={{ fontSize: 'var(--fs-help)' }}>
              另有 {summary?.hot_pending ?? 0} 条热点待处理
            </span>
          </div>
        </Card>
        <Card>
          <div className="kpi">
            <b>{summary ? summary.artifacts_last_7d : <Skeleton width={36} height={22} />}</b>
            <span>近 7 天产出</span>
            <span className="mut2" style={{ fontSize: 'var(--fs-help)' }}>
              sent {summary?.records_last_7d.sent ?? 0} · failed {summary?.records_last_7d.failed ?? 0}
            </span>
          </div>
        </Card>
      </div>

      <div className="grid2" style={{ alignItems: 'start' }}>
        <Card
          title="今日待办"
          actions={
            <Chip tone="outline">{summary ? `${summary.todo_items.length} 项` : '…'}</Chip>
          }
          bodyStyle={{ padding: '4px 16px 8px' }}
        >
          {summary === null ? (
            failed ? (
              <p className="mut" style={{ padding: '10px 0', fontSize: 12.5 }}>
                待办随概览一起没拉到，刷新再试。
              </p>
            ) : (
              <div className="stack" style={{ gap: 8, padding: '10px 0' }}>
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} width="88%" height={18} />
                ))}
              </div>
            )
          ) : summary.todo_items.length === 0 ? (
            <EmptyState
              title="今天没有待办"
              description="排期、进行中选题、今日日程、待处理热点都是空的。"
              actionLabel="去选题库"
              onAction={() => navigate('/topics')}
            />
          ) : (
            summary.todo_items.map((item) => {
              const meta = TODO_META[item.kind]
              const Icon = meta.icon
              return (
                <div className="task" key={`${item.kind}-${item.title}`} onClick={() => navigate(item.to)}>
                  <div className="ti">
                    <Icon size={14} />
                  </div>
                  <div className="tx">
                    <b>{item.title}</b>
                    <span>{meta.sub}</span>
                  </div>
                  <Chip tone={meta.tone}>{meta.label}</Chip>
                </div>
              )
            })
          )}
        </Card>

        <Card
          title="快捷入口"
          actions={
            <Button size="sm" variant="ghost" iconRight={ArrowRight} onClick={() => navigate('/capability')}>
              全部能力
            </Button>
          }
        >
          <div className="quick">
            <button type="button" onClick={() => ask('帮我做「小红书知识卡」')}>
              <div className="qi">
                <ImageIcon size={15} />
              </div>
              <div>
                <b>做成品</b>
                <span>小红书知识卡 · 1080×1440</span>
              </div>
            </button>
            <button type="button" onClick={() => ask('帮我做「一键成片」')}>
              <div className="qi">
                <MonitorPlay size={15} />
              </div>
              <div>
                <b>出视频</b>
                <span>一键成片 · 主题直接出竖版</span>
              </div>
            </button>
            <button type="button" onClick={() => navigate('/hot')}>
              <div className="qi">
                <Flame size={15} />
              </div>
              <div>
                <b>找选题</b>
                <span>热点素材池 + 订阅聚合</span>
              </div>
            </button>
            <button type="button" onClick={() => navigate('/analytics')}>
              <div className="qi">
                <BarChart3 size={15} />
              </div>
              <div>
                <b>看数据</b>
                <span>录入表现 · 复盘沉淀（下方有看板）</span>
              </div>
            </button>
          </div>
        </Card>
      </div>

      <div className="grid2" style={{ alignItems: 'start' }}>
        <Card
          title="今日热点速览"
          actions={
            <>
              <Chip tone="outline">素材池待处理</Chip>
              <Button size="sm" variant="ghost" onClick={() => navigate('/hot')}>
                进入发现
              </Button>
            </>
          }
          bodyStyle={{ padding: '2px 16px 6px' }}
        >
          {hotFeed === null ? (
            <div className="stack" style={{ gap: 8, padding: '10px 0' }}>
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} width="90%" height={18} />
              ))}
            </div>
          ) : hotFeed.length === 0 ? (
            <EmptyState
              icon={<Flame size={22} />}
              title="热点素材池是空的"
              description="到「热点发现」导入热点或抓取订阅，攒素材生成日报。"
              actionLabel="去发现"
              onAction={() => navigate('/hot')}
            />
          ) : (
            hotFeed.map((e, i) => (
              <div
                className="feed-item"
                key={e.id}
                onClick={() => ask(`围绕这个热点帮我做一条内容：「${e.title}」。先给 3 个切入角度，再出完整成稿。`)}
              >
                <span className={`feed-rank ${i < 3 ? 'hot' : ''}`}>{i + 1}</span>
                <div className="feed-b">
                  <b>{e.title}</b>
                  <div className="feed-m">
                    <span>{e.entry_date}</span>
                    <Chip tone="outline" xs>
                      {e.platform || '未知平台'}
                    </Chip>
                    {e.heat ? <span className="spark">{e.heat}</span> : null}
                  </div>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  style={{ opacity: 0 }}
                  onMouseEnter={(ev) => (ev.currentTarget.style.opacity = '1')}
                  onMouseLeave={(ev) => (ev.currentTarget.style.opacity = '0')}
                  onClick={(ev) => {
                    ev.stopPropagation()
                    ask(`围绕这个热点帮我做一条内容：「${e.title}」。先给 3 个切入角度，再出完整成稿。`)
                  }}
                >
                  做成内容
                </Button>
              </div>
            ))
          )}
        </Card>

        <Card
          title="最近产出"
          actions={
            <Button size="sm" variant="ghost" onClick={() => navigate('/library')}>
              内容库
            </Button>
          }
        >
          {summary === null ? (
            <div className="stack" style={{ gap: 8 }}>
              <Skeleton width="90%" height={18} />
              <Skeleton width="60%" height={18} />
            </div>
          ) : (
            <div className="stack" style={{ gap: 10 }}>
              <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
                <div style={{ flex: 1, minWidth: 120 }}>
                  <div className="mut2" style={{ fontSize: 11, marginBottom: 5 }}>
                    近 7 天发送成功
                  </div>
                  <Chip tone="accent">{summary.records_last_7d.sent} 条</Chip>
                </div>
                <div style={{ flex: 1, minWidth: 120 }}>
                  <div className="mut2" style={{ fontSize: 11, marginBottom: 5 }}>
                    近 7 天发送失败
                  </div>
                  <Chip tone={summary.records_last_7d.failed > 0 ? 'danger' : 'outline'}>
                    {summary.records_last_7d.failed} 条
                  </Chip>
                </div>
              </div>
              {summary.records_last_7d.failed > 0 ? (
                <div className="sysfile danger" style={{ marginBottom: 0 }}>
                  有失败记录
                  <Button size="sm" variant="ghost" onClick={() => navigate('/publish')}>
                    去发布中心看原因
                  </Button>
                </div>
              ) : null}
              <div className="hr" />
              <button
                type="button"
                className="mut"
                style={{
                  fontSize: 12,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 7,
                  background: 'none',
                  border: 0,
                  padding: 0,
                  cursor: 'pointer',
                  color: 'var(--muted)',
                }}
                onClick={scrollToDashboard}
              >
                <TrendingUp size={14} style={{ color: 'var(--accent)' }} />
                数据看板见下方（真实录入数据）
              </button>
            </div>
          )}
        </Card>
      </div>

      <DashboardSection />
    </div>
  )
}

export default WorkbenchPage
