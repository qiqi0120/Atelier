/** SPEC-09 · 内容日历页（M2-2 前半，占位页转正）。
 *
 * 布局：PageHead（月份导航 + 导入节点 + 新建事件 + 生成建议 primary）→ 近 14 天
 * 节点条（查询式提醒，SPEC-09 §3）→ 月视图网格（周日起始 42 格，原型同款 cal-* 样式）。
 * 格内条目三类：选题条目（.ev accent，点击去选题库）· 日历节点（.ev.act 斜纹，
 * 点击进编辑弹层）。平台活动与其他事件都用斜纹只读视觉，kind 靠文字前缀区分。
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CalendarDays, ChevronLeft, ChevronRight, Download, Sparkles } from 'lucide-react'
import { Button, Card, Chip, ConfirmDialog, EmptyState, toast } from '@/components'
import { PageHead } from '@/features/shared/PageHead'
import { calendarApi } from './api'
import { EventDialog } from './EventDialog'
import { SuggestDialog } from './SuggestDialog'
import { KIND_LABEL, KIND_PREFIX, type CalEvent, type MonthView, type UpcomingItem } from './types'

const pad = (n: number) => String(n).padStart(2, '0')

function currentMonth(): string {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`
}

function todayIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function monthLabel(month: string): string {
  const [y, m] = month.split('-')
  return `${y}年${Number(m)}月`
}

function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(y, m - 1 + delta, 1)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`
}

function addDaysIso(iso: string, n: number): string {
  const [y, m, d] = iso.split('-').map(Number)
  const dt = new Date(y, m - 1, d + n)
  return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`
}

/** 周日起始的 42 个月格（原型同款：2026-09-27 是周日） */
function monthCells(month: string): { iso: string; day: number; out: boolean }[] {
  const [y, m] = month.split('-').map(Number)
  const first = new Date(y, m - 1, 1)
  const start = new Date(y, m - 1, 1 - first.getDay())
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)
    return {
      iso: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
      day: d.getDate(),
      out: d.getMonth() !== m - 1,
    }
  })
}

/** 多日活动展开到占用的每一天（服务端保证 end_date >= date；护栏防脏数据死循环） */
function expandDays(ev: CalEvent): string[] {
  const out: string[] = []
  const end = ev.end_date || ev.date
  let cur = ev.date
  for (let guard = 0; cur <= end && guard < 62; guard += 1) {
    out.push(cur)
    cur = addDaysIso(cur, 1)
  }
  return out
}

const WEEK_HEAD = ['日', '一', '二', '三', '四', '五', '六']

export function CalendarPage() {
  const navigate = useNavigate()
  const [month, setMonth] = useState(currentMonth)
  const [view, setView] = useState<MonthView | null>(null)
  const [upcoming, setUpcoming] = useState<UpcomingItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [seeding, setSeeding] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<CalEvent | null>(null)
  const [deleting, setDeleting] = useState<CalEvent | null>(null)
  const [suggestOpen, setSuggestOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [v, u] = await Promise.all([calendarApi.month(month), calendarApi.upcoming(14)])
      setView(v)
      setUpcoming(u.items)
      setError('')
    } catch {
      // api 层已 toast；页面里再放一条静态错误说明
      setError('日历加载失败，确认服务在跑后点重试')
    } finally {
      setLoading(false)
    }
  }, [month])

  useEffect(() => {
    void load()
  }, [load])

  const eventsByDay = useMemo(() => {
    const map = new Map<string, CalEvent[]>()
    for (const ev of view?.events ?? []) {
      for (const iso of expandDays(ev)) {
        const list = map.get(iso) ?? []
        list.push(ev)
        map.set(iso, list)
      }
    }
    return map
  }, [view?.events])

  const topicsByDay = useMemo(() => {
    const map = new Map<string, MonthView['topics']>()
    for (const t of view?.topics ?? []) {
      const list = map.get(t.due_date) ?? []
      list.push(t)
      map.set(t.due_date, list)
    }
    return map
  }, [view?.topics])

  const doSeed = async () => {
    setSeeding(true)
    try {
      const r = await calendarApi.seed()
      toast.ok(`已导入 ${r.added} 个内置节点${r.skipped ? `（${r.skipped} 个已存在跳过）` : ''}`)
      await load()
    } finally {
      setSeeding(false)
    }
  }

  const removeEvent = async (id: string) => {
    await calendarApi.remove(id)
    toast.ok('节点已删除')
    setEditing(null)
    await load()
  }

  const tIso = todayIso()
  const cells = monthCells(month)

  return (
    <div className="view-pad">
      <PageHead
        title="内容日历"
        desc="事件、节点与选题排期在一个月历上；建议一键落选题池。"
        actions={
          <>
            <div className="row" style={{ gap: 4, alignItems: 'center' }}>
              <Button icon={ChevronLeft} aria-label="上一个月" onClick={() => setMonth((m) => shiftMonth(m, -1))} />
              <span
                style={{ fontSize: 13.5, fontWeight: 600, minWidth: 92, textAlign: 'center' }}
                data-testid="month-label"
              >
                {monthLabel(month)}
              </span>
              <Button icon={ChevronRight} aria-label="下一个月" onClick={() => setMonth((m) => shiftMonth(m, 1))} />
              <Button size="sm" onClick={() => setMonth(currentMonth())}>
                本月
              </Button>
            </div>
            <Button icon={Download} loading={seeding} onClick={() => void doSeed()}>
              导入本年节点
            </Button>
            <Button icon={CalendarDays} onClick={() => setCreateOpen(true)}>
              新建事件
            </Button>
            <Button variant="primary" icon={Sparkles} onClick={() => setSuggestOpen(true)}>
              生成近 14 天建议
            </Button>
          </>
        }
      />

      {error ? (
        <p className="sysfile danger">
          {error} <button type="button" className="btn ghost sm" onClick={() => void load()}><span className="btn-txt">重试</span></button>
        </p>
      ) : null}

      {upcoming.length > 0 ? (
        <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }} data-testid="upcoming-strip">
          <span style={{ fontSize: 12.5, color: 'var(--ink-3)' }}>近 14 天：</span>
          {upcoming.map((u) => (
            <Chip
              key={u.id}
              tone={u.remind_active ? 'accent' : 'outline'}
              title={`${KIND_LABEL[u.kind]} · 提前 ${u.remind_days} 天提醒`}
              onClick={() => setEditing(u)}
            >
              {u.date.slice(5)} {u.title}
              {u.days_left > 0 ? ` · 还有 ${u.days_left} 天` : u.days_left === 0 ? ' · 今天' : ' · 进行中'}
            </Chip>
          ))}
        </div>
      ) : loading ? null : (
        <p style={{ margin: '0 0 12px', fontSize: 12.5, color: 'var(--muted)' }}>
          近 14 天没有节点。可以先「导入本年节点」，或自己新建事件。
        </p>
      )}

      <Card tight>
        <div className="cal" data-testid="cal-grid">
          <div className="cal-h">
            {WEEK_HEAD.map((d) => (
              <div key={d}>{d}</div>
            ))}
          </div>
          <div className="cal-g">
            {cells.map((c) => (
              <div key={c.iso} className={`cal-d ${c.out ? 'out' : ''} ${c.iso === tIso ? 'today' : ''}`}>
                <span className="dn">{c.day}</span>
                {(eventsByDay.get(c.iso) ?? []).map((ev) => (
                  <span
                    key={ev.id}
                    className="ev act"
                    title={`${KIND_LABEL[ev.kind]} · ${ev.title}${ev.note ? `（${ev.note}）` : ''}`}
                    onClick={() => setEditing(ev)}
                  >
                    {KIND_PREFIX[ev.kind]}·{ev.title}
                  </span>
                ))}
                {(topicsByDay.get(c.iso) ?? []).map((t) => (
                  <span
                    key={t.id}
                    className="ev"
                    title={`选题 · ${t.title}（去选题库处理）`}
                    onClick={() => navigate('/topics')}
                  >
                    {t.title}
                  </span>
                ))}
              </div>
            ))}
          </div>
        </div>
        <div className="legend" style={{ padding: '10px 12px' }}>
          <span>
            <i className="k-wait" />
            内容条目（选题，点击去选题库）
          </span>
          <span>
            <i style={{ background: 'var(--surface-2)', border: '1px dashed var(--line)' }} />
            日历节点（斜纹只读，点击编辑）
          </span>
        </div>
      </Card>

      {!loading && view && view.events.length === 0 && view.topics.length === 0 ? (
        <Card tight>
          <EmptyState
            icon={<CalendarDays size={22} />}
            title="这个月还是空的"
            description="导入本年内置节点，或者新建一个属于你自己的事件；然后让 AI 结合节点出近 14 天选题。"
            actionLabel="导入本年节点"
            onAction={() => void doSeed()}
          />
        </Card>
      ) : null}

      <EventDialog
        open={createOpen || editing !== null}
        event={editing}
        onClose={() => {
          setCreateOpen(false)
          setEditing(null)
        }}
        onSaved={() => void load()}
        onRequestDelete={(ev) => setDeleting(ev)}
      />
      <SuggestDialog open={suggestOpen} onClose={() => setSuggestOpen(false)} onSaved={() => void load()} />
      <ConfirmDialog
        open={deleting !== null}
        title="删除这个节点？"
        sub={deleting ? `「${deleting.title}」将从日历移除，不可恢复；内置节点重新导入会带回。` : undefined}
        okText="删除节点"
        danger
        onCancel={() => setDeleting(null)}
        onConfirm={() => {
          if (deleting) void removeEvent(deleting.id)
          setDeleting(null)
        }}
      />
    </div>
  )
}

export default CalendarPage
