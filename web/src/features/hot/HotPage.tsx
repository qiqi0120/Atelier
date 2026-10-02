/** SPEC-12 §4 · 热点发现页（M2-3b，占位页转正）。
 *
 * 三 Tab：素材池（热点 entries → 日报/存选题库/做成内容）·
 * 订阅源（RSS/手填订阅 + feed 聚合 + UGC 搜索）· 算法追踪（手工时间线）。
 * 诚实边界固定展示：7 源自动热榜无公开数据源，当前支持订阅聚合 + 手工导入。
 */

import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  CalendarClock,
  CloudDownload,
  Newspaper as FeedIcon,
  Flame,
  GitBranch,
  Import,
  Plus,
  Rss,
  Save,
  Search,
  Send,
  Trash2,
} from 'lucide-react'
import {
  Button,
  Card,
  Chip,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  Modal,
  Select,
  Tabs,
  Textarea,
  toast,
} from '@/components'
import { PageHead } from '@/features/shared/PageHead'
import { useAtelier } from '@/lib/store'
import { describeError } from '@/lib/gates'
import { topicsApi } from '@/features/topics/api'
import { discoveryApi } from './api'
import { DigestDialog } from './DigestDialog'
import { GapsDialog } from './GapsDialog'
import { DigestHistoryDrawer } from './DigestHistoryDrawer'
import {
  HOT_STATUS_LABEL,
  HOT_STATUS_TONE,
  SUB_KIND_LABEL,
  type AlgorithmNote,
  type FeedItem,
  type HotEntry,
  type Subscription,
} from './types'

type TabKey = 'pool' | 'subs' | 'algo'

export function HotPage() {
  const navigate = useNavigate()
  const profile = useAtelier((s) => s.profile)
  const fillPrompt = useAtelier((s) => s.fillPrompt)
  const profileId = profile && !profile.generalMode ? profile.id : undefined

  const [tab, setTab] = useState<TabKey>('pool')
  const [loading, setLoading] = useState(true)
  const [errorText, setErrorText] = useState('')

  const [entries, setEntries] = useState<HotEntry[]>([])
  const [counts, setCounts] = useState<Record<HotEntry['status'], number>>({
    pending: 0,
    digested: 0,
    archived: 0,
  })
  const [statusFilter, setStatusFilter] = useState<'' | HotEntry['status']>('')

  const [subs, setSubs] = useState<Subscription[]>([])
  const [feed, setFeed] = useState<FeedItem[]>([])
  const [notes, setNotes] = useState<AlgorithmNote[]>([])

  // 弹层开关
  const [digestOpen, setDigestOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [gapsOpen, setGapsOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [fromFeedOpen, setFromFeedOpen] = useState(false)
  const [subModal, setSubModal] = useState<null | { mode: 'create' } | { mode: 'edit'; sub: Subscription }>(null)
  const [ingestFor, setIngestFor] = useState<Subscription | null>(null)
  const [noteOpen, setNoteOpen] = useState(false)
  const [deleting, setDeleting] = useState<null | { kind: 'sub' | 'note'; id: string; name: string }>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setErrorText('')
    try {
      const [hotR, subsR, feedR, notesR] = await Promise.all([
        discoveryApi.hot(statusFilter),
        discoveryApi.listSubscriptions(),
        discoveryApi.feed({ days: 7, limit: 50 }),
        discoveryApi.algorithmNotes(),
      ])
      setEntries(hotR.items)
      setCounts(hotR.counts)
      setSubs(subsR.items)
      setFeed(feedR.items)
      setNotes(notesR.items)
    } catch (e) {
      setErrorText(describeError(e))
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => {
    void load()
  }, [load])

  /** F-D3 存选题库：source=hot 可溯源（SPEC-12 §0 D7） */
  const saveTopic = async (entry: { title: string; url?: string; entry_date?: string }) => {
    try {
      await topicsApi.create({
        title: entry.title.slice(0, 80),
        source: 'hot',
        source_ref: entry.url || `热点素材 ${entry.entry_date ?? ''}`.trim(),
      })
      toast.ok('已存入选题库「待做」列，带热点来源')
    } catch {
      /* api 层已 toast */
    }
  }

  /** F-D4 做成内容：只填入不发送（UI-SPEC 规则 1） */
  const compose = (title: string) => {
    fillPrompt(
      `围绕这个热点帮我做一条内容：「${title}」。\n先给 3 个切入角度（蹭热点但不硬蹭），选定后出完整成稿。`,
    )
    navigate('/chat')
  }

  const archive = async (entry: HotEntry) => {
    try {
      await discoveryApi.archiveHot(entry.id, 'archived')
      toast.ok('已归档')
      void load()
    } catch {
      /* api 层已 toast */
    }
  }

  const tabItems = [
    { key: 'pool', label: `素材池${counts.pending ? ` (${counts.pending})` : ''}` },
    { key: 'subs', label: `订阅源${subs.length ? ` (${subs.length})` : ''}` },
    { key: 'algo', label: '算法追踪' },
  ]

  return (
    <div className="view-pad">
      <PageHead
        title="热点发现"
        desc="订阅聚合 + 手工导入双数据源。热点素材池 → 日报 → 选题库，来源全程可溯。"
        actions={
          <>
            <Button icon={GitBranch} onClick={() => setGapsOpen(true)}>
              内容缺口
            </Button>
            <Button icon={FeedIcon} onClick={() => setHistoryOpen(true)}>
              日报历史
            </Button>
            <Button variant="primary" icon={Flame} onClick={() => setDigestOpen(true)}>
              生成日报
            </Button>
          </>
        }
      />

      <p className="sysfile" data-testid="hot-notice">
        诚实边界：抖音/微博/小红书等平台没有公开热点 API，7 源自动热榜暂不可做；当前数据源 =
        订阅 RSS 聚合 + 手工导入，两者都是真数据。
      </p>

      <Tabs items={tabItems} value={tab} onChange={(k) => setTab(k as TabKey)} ariaLabel="发现域视图" />

      {errorText ? (
        <p className="sysfile danger">
          {errorText}{' '}
          <button type="button" className="btn ghost sm" onClick={() => void load()}>
            <span className="btn-txt">重试</span>
          </button>
        </p>
      ) : null}

      {loading ? (
        <Card title="加载中…" tight>
          <div style={{ height: 120 }} />
        </Card>
      ) : tab === 'pool' ? (
        <PoolView
          entries={entries}
          counts={counts}
          statusFilter={statusFilter}
          onFilter={setStatusFilter}
          onSaveTopic={saveTopic}
          onCompose={compose}
          onArchive={archive}
          onImport={() => setImportOpen(true)}
          onFromFeed={() => setFromFeedOpen(true)}
        />
      ) : tab === 'subs' ? (
        <SubsView
          subs={subs}
          feed={feed}
          onFetchAll={async () => {
            const r = await discoveryApi.fetchAll()
            toast.ok(`抓取完成：${r.ok_count}/${r.total} 个源成功，新增 ${r.inserted} 条`)
            void load()
          }}
          onFetch={async (sub) => {
            const r = await discoveryApi.fetchSubscription(sub.id)
            toast.ok(`「${sub.name}」新增 ${r.inserted} 条（源提供 ${r.parsed}，过滤 ${r.filtered}）`)
            void load()
          }}
          onCreate={() => setSubModal({ mode: 'create' })}
          onEdit={(sub) => setSubModal({ mode: 'edit', sub })}
          onIngest={(sub) => setIngestFor(sub)}
          onDelete={(sub) => setDeleting({ kind: 'sub', id: sub.id, name: sub.name })}
          onCompose={compose}
          onSaveTopic={saveTopic}
        />
      ) : (
        <AlgoView
          notes={notes}
          onAdd={() => setNoteOpen(true)}
          onDelete={(n) => setDeleting({ kind: 'note', id: n.id, name: `${n.platform} ${n.noted_at}` })}
        />
      )}

      <DigestDialog
        open={digestOpen}
        onClose={() => setDigestOpen(false)}
        profileId={profileId}
        onDone={() => void load()}
      />
      <GapsDialog open={gapsOpen} onClose={() => setGapsOpen(false)} profileId={profileId} />
      <DigestHistoryDrawer open={historyOpen} onClose={() => setHistoryOpen(false)} />
      <ImportHotModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onDone={() => {
          setImportOpen(false)
          void load()
        }}
      />
      <FromFeedModal
        open={fromFeedOpen}
        feed={feed}
        onClose={() => setFromFeedOpen(false)}
        onDone={(ids) => {
          setFromFeedOpen(false)
          discoveryApi
            .hotFromFeed(ids)
            .then((r) => {
              toast.ok(`转入素材池 ${r.inserted} 条${r.skipped.length ? `，跳过 ${r.skipped.length} 条（重复/缺失）` : ''}`)
              void load()
            })
            .catch(() => {})
        }}
      />
      <SubModal
        state={subModal}
        onClose={() => setSubModal(null)}
        onDone={() => {
          setSubModal(null)
          void load()
        }}
      />
      <IngestModal
        sub={ingestFor}
        onClose={() => setIngestFor(null)}
        onDone={() => {
          setIngestFor(null)
          void load()
        }}
      />
      <NoteModal
        open={noteOpen}
        onClose={() => setNoteOpen(false)}
        onDone={() => {
          setNoteOpen(false)
          void load()
        }}
      />
      <ConfirmDialog
        open={deleting !== null}
        title={deleting?.kind === 'sub' ? '删除订阅？' : '删除这条算法记录？'}
        sub={`将删除「${deleting?.name ?? ''}」${deleting?.kind === 'sub' ? '及其全部 feed 条目' : ''}，不可恢复。`}
        danger
        onCancel={() => setDeleting(null)}
        onConfirm={async () => {
          if (!deleting) return
          try {
            if (deleting.kind === 'sub') await discoveryApi.deleteSubscription(deleting.id)
            else await discoveryApi.deleteAlgorithmNote(deleting.id)
            toast.ok('已删除')
          } finally {
            setDeleting(null)
            void load()
          }
        }}
      />
    </div>
  )
}

/** 素材池视图 */
function PoolView(props: {
  entries: HotEntry[]
  counts: Record<HotEntry['status'], number>
  statusFilter: '' | HotEntry['status']
  onFilter: (s: '' | HotEntry['status']) => void
  onSaveTopic: (e: HotEntry) => void
  onCompose: (title: string) => void
  onArchive: (e: HotEntry) => void
  onImport: () => void
  onFromFeed: () => void
}) {
  return (
    <Card
      title="热点素材池"
      actions={
        <>
          <Select
            sizeSm
            aria-label="按状态筛选"
            value={props.statusFilter}
            onChange={(e) => props.onFilter(e.target.value as '' | HotEntry['status'])}
            options={[
              { value: '', label: `全部 (${Object.values(props.counts).reduce((a, b) => a + b, 0)})` },
              ...(Object.keys(HOT_STATUS_LABEL) as HotEntry['status'][]).map((s) => ({
                value: s,
                label: `${HOT_STATUS_LABEL[s]} (${props.counts[s]})`,
              })),
            ]}
          />
          <Button size="sm" icon={CloudDownload} onClick={props.onFromFeed}>
            从订阅转入
          </Button>
          <Button size="sm" icon={Import} onClick={props.onImport}>
            手工导入
          </Button>
        </>
      }
      bodyStyle={{ padding: '2px 16px 8px' }}
    >
      {props.entries.length === 0 ? (
        <EmptyState
          icon={<Flame size={22} />}
          title="素材池还是空的"
          description="从订阅 feed 一键转入，或手工粘贴你看到的热点；攒够素材就能生成结构化日报。"
          actionLabel="去订阅源看看"
          onAction={() => undefined}
        />
      ) : (
        props.entries.map((e) => (
          <div className="task" key={e.id} data-testid="hot-entry">
            <div className="ti">
              <Flame size={14} />
            </div>
            <div className="tx">
              <b>{e.title}</b>
              <span>
                {e.entry_date} · {e.platform || '未知平台'}
                {e.heat ? ` · ${e.heat}` : ''}
                {e.note ? ` · ${e.note}` : ''}
              </span>
            </div>
            <Chip tone={HOT_STATUS_TONE[e.status]}>{HOT_STATUS_LABEL[e.status]}</Chip>
            <div className="row" style={{ gap: 4 }}>
              <Button size="sm" variant="ghost" icon={Save} onClick={() => props.onSaveTopic(e)}>
                存选题
              </Button>
              <Button size="sm" variant="ghost" icon={Send} onClick={() => props.onCompose(e.title)}>
                做成内容
              </Button>
              {e.status === 'pending' ? (
                <Button size="sm" variant="ghost" onClick={() => props.onArchive(e)}>
                  归档
                </Button>
              ) : null}
            </div>
          </div>
        ))
      )}
    </Card>
  )
}

/** 订阅源视图（订阅 CRUD + feed 聚合 + UGC 搜索） */
function SubsView(props: {
  subs: Subscription[]
  feed: FeedItem[]
  onFetchAll: () => Promise<void>
  onFetch: (sub: Subscription) => Promise<void>
  onCreate: () => void
  onEdit: (sub: Subscription) => void
  onIngest: (sub: Subscription) => void
  onDelete: (sub: Subscription) => void
  onCompose: (title: string) => void
  onSaveTopic: (entry: { title: string; url?: string; entry_date?: string }) => void
}) {
  const [ugcQ, setUgcQ] = useState('')
  const [ugcItems, setUgcItems] = useState<FeedItem[] | null>(null)
  const [ugcNotice, setUgcNotice] = useState('')
  const [picked, setPicked] = useState<Set<string>>(new Set())

  const searchUgc = async () => {
    if (!ugcQ.trim()) return
    try {
      const r = await discoveryApi.ugc(ugcQ.trim())
      setUgcItems(r.items)
      setUgcNotice(r.notice)
    } catch {
      /* api 层已 toast */
    }
  }

  const togglePick = (id: string) => {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="stack" style={{ gap: 14 }}>
      <Card
        title="订阅源"
        actions={
          <>
            <Button size="sm" icon={CloudDownload} onClick={() => void props.onFetchAll()}>
              全部抓取
            </Button>
            <Button size="sm" variant="primary" icon={Plus} onClick={props.onCreate}>
              新建订阅
            </Button>
          </>
        }
        bodyStyle={{ padding: '2px 16px 8px' }}
      >
        {props.subs.length === 0 ? (
          <EmptyState
            icon={<Rss size={22} />}
            title="还没有订阅"
            description="订阅博主的 RSS（自动抓取聚合），没有 RSS 的博主建「手填」订阅粘贴内容。"
            actionLabel="新建第一个订阅"
            onAction={props.onCreate}
          />
        ) : (
          props.subs.map((s) => (
            <div className="task" key={s.id} data-testid="sub-row">
              <div className="ti">
                <Rss size={14} />
              </div>
              <div className="tx">
                <b>{s.name}</b>
                <span>
                  {SUB_KIND_LABEL[s.kind]} · {s.source === 'rss' ? 'RSS 自动' : '手填'}
                  {s.platform ? ` · ${s.platform}` : ''}
                  {s.keywords.length ? ` · 关键词：${s.keywords.join('/')}` : ''}
                  {s.last_fetched_at ? ` · 上次抓取 ${s.last_fetched_at.slice(5, 16).replace('T', ' ')}` : ''}
                </span>
              </div>
              {!s.enabled ? <Chip tone="neutral">已停用</Chip> : null}
              <div className="row" style={{ gap: 4 }}>
                {s.source === 'rss' ? (
                  <Button size="sm" variant="ghost" onClick={() => void props.onFetch(s)}>
                    抓取
                  </Button>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => props.onIngest(s)}>
                    手填
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => props.onEdit(s)}>
                  编辑
                </Button>
                <Button size="sm" variant="ghost" icon={Trash2} onClick={() => props.onDelete(s)}>
                  删除
                </Button>
              </div>
            </div>
          ))
        )}
      </Card>

      <Card title="最近 7 天聚合内容" bodyStyle={{ padding: '2px 16px 8px' }}>
        <div className="row" style={{ gap: 8, padding: '8px 0' }} data-testid="ugc-search">
          <Input
            sizeSm
            placeholder="在订阅内容里搜（UGC 发现）…"
            aria-label="UGC 搜索词"
            value={ugcQ}
            style={{ width: 220 }}
            onChange={(e) => setUgcQ(e.target.value)}
          />
          <Button size="sm" icon={Search} onClick={() => void searchUgc()}>
            搜索
          </Button>
        </div>
        {ugcNotice ? <p className="sysfile">{ugcNotice}</p> : null}
        {props.feed.length === 0 ? (
          <EmptyState
            icon={<FeedIcon size={22} />}
            title="近 7 天没有聚合内容"
            description="点订阅行的「抓取」，或给订阅配关键词过滤。"
          />
        ) : (
          (ugcItems ?? props.feed).map((f) => (
            <div className="task" key={f.id} data-testid="feed-row">
              <input
                type="checkbox"
                aria-label={`选择：${f.title}`}
                checked={picked.has(f.id)}
                onChange={() => togglePick(f.id)}
              />
              <div className="tx">
                <b>{f.title}</b>
                <span>
                  来自 {f.subscription_name}
                  {f.published_at ? ` · ${f.published_at.slice(0, 10)}` : ''}
                </span>
              </div>
              <div className="row" style={{ gap: 4 }}>
                <Button size="sm" variant="ghost" onClick={() => props.onSaveTopic(f)}>
                  存选题
                </Button>
                <Button size="sm" variant="ghost" icon={Send} onClick={() => props.onCompose(f.title)}>
                  做成内容
                </Button>
              </div>
            </div>
          ))
        )}
        {picked.size ? (
          <div className="row" style={{ gap: 8, padding: '8px 0' }}>
            <Button
              size="sm"
              variant="primary"
              icon={Import}
              onClick={() => {
                discoveryApi
                  .hotFromFeed([...picked])
                  .then((r) => {
                    toast.ok(`转入素材池 ${r.inserted} 条`)
                    setPicked(new Set())
                  })
                  .catch(() => {})
              }}
            >
              转入选中 {picked.size} 条
            </Button>
          </div>
        ) : null}
      </Card>
    </div>
  )
}

/** 算法追踪视图（手工时间线，固定诚实标注） */
function AlgoView(props: {
  notes: AlgorithmNote[]
  onAdd: () => void
  onDelete: (n: AlgorithmNote) => void
}) {
  return (
    <Card
      title="算法/审核规则变化时间线"
      actions={
        <Button size="sm" variant="primary" icon={Plus} onClick={props.onAdd}>
          登记变化
        </Button>
      }
      bodyStyle={{ padding: '2px 16px 8px' }}
    >
      <p className="sysfile">自动追踪没有数据源（平台不公开规则变更流），当前是手工登记时间线。</p>
      {props.notes.length === 0 ? (
        <EmptyState
          icon={<CalendarClock size={22} />}
          title="还没有登记"
          description="刷到平台规则变化的讨论就记一条：平台、日期、改了什么、对你内容的影响。"
          actionLabel="登记第一条"
          onAction={props.onAdd}
        />
      ) : (
        props.notes.map((n) => (
          <div className="task" key={n.id} data-testid="algo-row">
            <div className="ti">
              <CalendarClock size={14} />
            </div>
            <div className="tx">
              <b>
                [{n.noted_at}] {n.platform}：{n.change}
              </b>
              <span>{n.impact ? `影响：${n.impact}` : '（未填影响）'}</span>
            </div>
            <Button size="sm" variant="ghost" icon={Trash2} onClick={() => props.onDelete(n)}>
              删除
            </Button>
          </div>
        ))
      )}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// 弹层
// ---------------------------------------------------------------------------

function ImportHotModal(props: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [title, setTitle] = useState('')
  const [platform, setPlatform] = useState('')
  const [url, setUrl] = useState('')
  const [heat, setHeat] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true)
    try {
      await discoveryApi.createHot({ title, platform, url, heat, note })
      toast.ok('已导入素材池')
      setTitle(''); setPlatform(''); setUrl(''); setHeat(''); setNote('')
      props.onDone()
    } catch {
      /* api 层已 toast */
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={props.open}
      onClose={props.onClose}
      title="手工导入热点"
      sub="粘贴你在热榜/群里看到的那条热点，来源如实标注"
      footer={
        <>
          <Button onClick={props.onClose}>取消</Button>
          <Button variant="primary" loading={busy} disabled={!title.trim()} onClick={() => void submit()}>
            导入
          </Button>
        </>
      }
    >
      <div className="stack" style={{ gap: 10 }}>
        <Field label="热点标题" required help="照榜上原样粘贴，别概括">
          {(id) => <Input id={id} value={title} onChange={(e) => setTitle(e.target.value)} />}
        </Field>
        <div className="row" style={{ gap: 10 }}>
          <Field label="平台" className="grow">
            {(id) => <Input id={id} value={platform} placeholder="抖音 / 微博…" onChange={(e) => setPlatform(e.target.value)} />}
          </Field>
          <Field label="热度（可选）" className="grow">
            {(id) => <Input id={id} value={heat} placeholder="榜3 / 1.2w" onChange={(e) => setHeat(e.target.value)} />}
          </Field>
        </div>
        <Field label="原文链接（可选）">
          {(id) => <Input id={id} value={url} onChange={(e) => setUrl(e.target.value)} />}
        </Field>
        <Field label="备注（可选）">
          {(id) => <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} />}
        </Field>
      </div>
    </Modal>
  )
}

function FromFeedModal(props: {
  open: boolean
  feed: FeedItem[]
  onClose: () => void
  onDone: (ids: string[]) => void
}) {
  const [picked, setPicked] = useState<Set<string>>(new Set())
  useEffect(() => {
    if (props.open) setPicked(new Set())
  }, [props.open])

  return (
    <Modal
      open={props.open}
      onClose={props.onClose}
      title="从订阅转入素材池"
      sub="勾选要转的条目；已转入过的会自动跳过"
      footer={
        <>
          <Button onClick={props.onClose}>取消</Button>
          <Button
            variant="primary"
            disabled={picked.size === 0}
            onClick={() => props.onDone([...picked])}
          >
            转入 {picked.size || ''} 条
          </Button>
        </>
      }
    >
      {props.feed.length === 0 ? (
        <EmptyState title="近 7 天没有聚合内容" description="先去「订阅源」抓取。" />
      ) : (
        props.feed.map((f) => (
          <label key={f.id} className="task" style={{ cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={picked.has(f.id)}
              onChange={() =>
                setPicked((prev) => {
                  const next = new Set(prev)
                  if (next.has(f.id)) next.delete(f.id)
                  else next.add(f.id)
                  return next
                })
              }
            />
            <div className="tx">
              <b>{f.title}</b>
              <span>来自 {f.subscription_name}</span>
            </div>
          </label>
        ))
      )}
    </Modal>
  )
}

function SubModal(props: {
  state: null | { mode: 'create' } | { mode: 'edit'; sub: Subscription }
  onClose: () => void
  onDone: () => void
}) {
  const editing = props.state?.mode === 'edit' ? props.state.sub : null
  const [name, setName] = useState('')
  const [kind, setKind] = useState<Subscription['kind']>('blogger')
  const [source, setSource] = useState<Subscription['source']>('rss')
  const [url, setUrl] = useState('')
  const [platform, setPlatform] = useState('')
  const [keywords, setKeywords] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (props.state) {
      setName(editing?.name ?? '')
      setKind(editing?.kind ?? 'blogger')
      setSource(editing?.source ?? 'rss')
      setUrl(editing?.url ?? '')
      setPlatform(editing?.platform ?? '')
      setKeywords(editing?.keywords.join(',') ?? '')
      setNotes(editing?.notes ?? '')
    }
  }, [props.state, editing])

  const submit = async () => {
    setBusy(true)
    try {
      const body = { name, kind, source, url, platform, keywords, notes }
      if (editing) await discoveryApi.updateSubscription(editing.id, body)
      else await discoveryApi.createSubscription(body)
      toast.ok(editing ? '订阅已更新' : '订阅已创建')
      props.onDone()
    } catch {
      /* api 层已 toast */
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={props.state !== null}
      onClose={props.onClose}
      title={editing ? '编辑订阅' : '新建订阅'}
      sub="有 RSS 地址的选「RSS 自动」；没有的建「手填」订阅，靠粘贴条目"
      footer={
        <>
          <Button onClick={props.onClose}>取消</Button>
          <Button variant="primary" loading={busy} disabled={!name.trim()} onClick={() => void submit()}>
            {editing ? '保存' : '创建'}
          </Button>
        </>
      }
    >
      <div className="stack" style={{ gap: 10 }}>
        <Field label="名称" required>
          {(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <div className="row" style={{ gap: 10 }}>
          <Field label="类型" className="grow">
            {(id) => (
              <Select
                id={id}
                value={kind}
                onChange={(e) => setKind(e.target.value as Subscription['kind'])}
                options={(Object.keys(SUB_KIND_LABEL) as Subscription['kind'][]).map((k) => ({
                  value: k,
                  label: SUB_KIND_LABEL[k],
                }))}
              />
            )}
          </Field>
          <Field label="数据源" className="grow">
            {(id) => (
              <Select
                id={id}
                value={source}
                onChange={(e) => setSource(e.target.value as Subscription['source'])}
                options={[
                  { value: 'rss', label: 'RSS 自动抓取' },
                  { value: 'manual', label: '手填' },
                ]}
              />
            )}
          </Field>
        </div>
        {source === 'rss' ? (
          <Field label="RSS 地址" required help="必须 http(s) 开头">
            {(id) => <Input id={id} value={url} onChange={(e) => setUrl(e.target.value)} />}
          </Field>
        ) : null}
        <div className="row" style={{ gap: 10 }}>
          <Field label="平台（可选）" className="grow">
            {(id) => <Input id={id} value={platform} onChange={(e) => setPlatform(e.target.value)} />}
          </Field>
          <Field label="关键词过滤（可选）" className="grow" help="逗号分隔，命中才入库">
            {(id) => <Input id={id} value={keywords} onChange={(e) => setKeywords(e.target.value)} />}
          </Field>
        </div>
        <Field label="备注（可选）">
          {(id) => <Textarea id={id} value={notes} onChange={(e) => setNotes(e.target.value)} />}
        </Field>
      </div>
    </Modal>
  )
}

function IngestModal(props: {
  sub: Subscription | null
  onClose: () => void
  onDone: () => void
}) {
  const [title, setTitle] = useState('')
  const [url, setUrl] = useState('')
  const [summary, setSummary] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (props.sub) {
      setTitle('')
      setUrl('')
      setSummary('')
    }
  }, [props.sub])

  const submit = async () => {
    if (!props.sub) return
    setBusy(true)
    try {
      const r = await discoveryApi.ingestManual(props.sub.id, { title, url, summary })
      toast.ok(r.inserted ? '条目已入库' : '该内容已在库里（去重）')
      props.onDone()
    } catch {
      /* api 层已 toast */
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={props.sub !== null}
      onClose={props.onClose}
      title={`手填条目 · ${props.sub?.name ?? ''}`}
      sub="粘贴这位博主的一条内容（标题 + 链接/摘要）"
      footer={
        <>
          <Button onClick={props.onClose}>取消</Button>
          <Button variant="primary" loading={busy} disabled={!title.trim()} onClick={() => void submit()}>
            入库
          </Button>
        </>
      }
    >
      <div className="stack" style={{ gap: 10 }}>
        <Field label="标题 / 开头一句" required>
          {(id) => <Input id={id} value={title} onChange={(e) => setTitle(e.target.value)} />}
        </Field>
        <Field label="链接（可选）">
          {(id) => <Input id={id} value={url} onChange={(e) => setUrl(e.target.value)} />}
        </Field>
        <Field label="摘要（可选）">
          {(id) => <Textarea id={id} value={summary} onChange={(e) => setSummary(e.target.value)} />}
        </Field>
      </div>
    </Modal>
  )
}

function NoteModal(props: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [platform, setPlatform] = useState('')
  const [notedAt, setNotedAt] = useState(new Date().toISOString().slice(0, 10))
  const [change, setChange] = useState('')
  const [impact, setImpact] = useState('')
  const [source, setSource] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true)
    try {
      await discoveryApi.createAlgorithmNote({ platform, noted_at: notedAt, change, impact, source })
      toast.ok('已登记')
      props.onDone()
    } catch {
      /* api 层已 toast */
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={props.open}
      onClose={props.onClose}
      title="登记平台规则变化"
      sub="刷到算法/审核规则变化的讨论就记一条，攒成自己的时间线"
      footer={
        <>
          <Button onClick={props.onClose}>取消</Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!platform.trim() || !change.trim()}
            onClick={() => void submit()}
          >
            登记
          </Button>
        </>
      }
    >
      <div className="stack" style={{ gap: 10 }}>
        <div className="row" style={{ gap: 10 }}>
          <Field label="平台" required className="grow">
            {(id) => <Input id={id} value={platform} placeholder="xhs / dy / gzh" onChange={(e) => setPlatform(e.target.value)} />}
          </Field>
          <Field label="日期" required className="grow">
            {(id) => (
              <Input id={id} type="date" value={notedAt} onChange={(e) => setNotedAt(e.target.value)} />
            )}
          </Field>
        </div>
        <Field label="改了什么" required>
          {(id) => <Textarea id={id} value={change} onChange={(e) => setChange(e.target.value)} />}
        </Field>
        <Field label="对内容的影响（可选）">
          {(id) => <Textarea id={id} value={impact} onChange={(e) => setImpact(e.target.value)} />}
        </Field>
        <Field label="消息来源（可选）">
          {(id) => <Input id={id} value={source} onChange={(e) => setSource(e.target.value)} />}
        </Field>
      </div>
    </Modal>
  )
}

export default HotPage
