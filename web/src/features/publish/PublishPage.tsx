import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Wand2 } from 'lucide-react'
import { Button, Chip, Skeleton, toast } from '@/components'
import { PageHead } from '@/features/shared/PageHead'
import { MasterEditor } from './MasterEditor'
import { MediaAttachments } from './MediaAttachments'
import { OptimizeDialog } from './OptimizeDialog'
import { PlatformPicker } from './PlatformPicker'
import { PlatformVariantCard } from './PlatformVariantCard'
import { PrecheckPanel } from './PrecheckPanel'
import { PublishConfirmDialog } from './PublishConfirmDialog'
import { PublishStatusList } from './PublishStatusList'
import { SmsDialog } from './SmsDialog'
import { publishApi } from './types'
import type {
  AdaptEvent,
  PlatformKey,
  PlatformMeta,
  PlatformRun,
  PrecheckResult,
  PublishDraft,
  PublishRecord,
  SchedulerStatus,
} from './types'

/**
 * 发布中心（SPEC-06 §7，照 `design/prototype-v1.html` 的 `#v-publish`）。
 *
 * 两条硬交互：
 * 1. 勾选平台 → 顶栏按钮文案变「发布到 N 个平台」
 * 2. 有硬门禁未解除时点发布 → toast「硬门禁未解除」**且不发**（后端也会 422 兜底）
 */
export function PublishPage() {
  const navigate = useNavigate()

  const [draft, setDraft] = useState<PublishDraft | null>(null)
  const [platforms, setPlatforms] = useState<PlatformMeta[]>([])
  const [selected, setSelected] = useState<PlatformKey[]>([])
  const [savedAt, setSavedAt] = useState<string | null>(null)
  const [adapting, setAdapting] = useState(false)
  const [stream, setStream] = useState<Record<string, string>>({})
  const [precheck, setPrecheck] = useState<PrecheckResult | null>(null)
  const [checking, setChecking] = useState(false)
  const [runs, setRuns] = useState<PlatformRun[]>([])
  const [records, setRecords] = useState<PublishRecord[]>([])
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [smsRecord, setSmsRecord] = useState<string | null>(null)
  const [booted, setBooted] = useState(false)
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null)
  const [optimizeOpen, setOptimizeOpen] = useState(false)
  const saveSeq = useRef(0)

  /* ---------------------------------------------------------- 初始化 */

  useEffect(() => {
    let alive = true
    const boot = async () => {
      try {
        const [meta, drafts] = await Promise.all([publishApi.platforms(), publishApi.listDrafts()])
        if (!alive) return
        setPlatforms(meta.platforms)
        const first = drafts.drafts[0]
        if (first) {
          setDraft(first)
          setSelected(first.variants.filter((v) => v.adapted || v.status !== 'pending').map((v) => v.platform))
          setSavedAt(first.updated_at)
          void publishApi
            .records(first.id)
            .then((r) => alive && setRecords(r.records))
            .catch(() => undefined)
        }
      } catch {
        /* ApiError 已自动 toast；页面保留空态而不是白屏 */
      } finally {
        if (alive) setBooted(true)
      }
    }
    void boot()
    return () => {
      alive = false
    }
  }, [])

  /* F-G20 调度器状态：页面加载拉一次即可（只读 Chip） */
  useEffect(() => {
    let alive = true
    publishApi
      .scheduler()
      .then((s) => {
        if (alive) setScheduler(s)
      })
      .catch(() => {
        /* 拉不到就不显示 Chip，不挡发布主流程 */
      })
    return () => {
      alive = false
    }
  }, [])

  /* ---------------------------------------------------------- 自动保存 */

  const save = useCallback(
    (patch: Partial<PublishDraft>) => {
      if (!draft) return
      const seq = ++saveSeq.current
      publishApi
        .patchDraft(draft.id, patch)
        .then((d) => {
          if (seq !== saveSeq.current) return // 丢弃过期响应
          setSavedAt(d.updated_at)
        })
        .catch(() => {
          /* 自动保存失败：不能打断编辑，但要留痕 */
          toast('草稿自动保存失败，刷新后可能丢这次改动', 'error')
        })
    },
    [draft],
  )

  const patch = useCallback(
    (p: Partial<PublishDraft>) => {
      setDraft((d) => (d ? { ...d, ...p } : d))
    },
    [],
  )

  /** F-G19：优化建议里一键替换标题 → 本地 patch（母版编辑器随 draft.title 重同步）+ 立即落库 */
  const replaceTitle = useCallback(
    (title: string) => {
      patch({ title })
      save({ title })
    },
    [patch, save],
  )

  /* ---------------------------------------------------------- 平台勾选 */

  const toggle = (p: PlatformKey) => {
    setSelected((cur) => {
      const next = cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]
      setPrecheck(null)
      return next
    })
  }

  /* ---------------------------------------------------------- 适配流 */

  const runAdapt = useCallback(
    async (targets?: PlatformKey[]) => {
      if (!draft) return
      const list = targets ?? selected
      if (list.length === 0) {
        toast('先勾选至少一个平台', 'warn')
        return
      }
      setAdapting(true)
      setStream({})
      setPrecheck(null)
      try {
        await publishApi.adapt(draft.id, list, (e: AdaptEvent) => {
          if (e.type === 'delta' && e.platform) {
            setStream((s) => ({ ...s, [e.platform as string]: e.acc ?? '' }))
          } else if (e.type === 'variant' && e.variant) {
            setDraft((d) =>
              d
                ? {
                    ...d,
                    variants: [...d.variants.filter((v) => v.platform !== e.platform), e.variant as never],
                  }
                : d,
            )
          } else if (e.type === 'error' && e.platform) {
            toast(`${e.platform} 适配失败：${e.message ?? '未知原因'}`, 'error')
          }
        })
        const fresh = await publishApi.getDraft(draft.id)
        setDraft(fresh)
        setSelected(fresh.variants.filter((v) => v.adapted || v.status !== 'pending').map((v) => v.platform))
        toast(`已适配 ${fresh.variants.filter((v) => v.adapted).length} 个平台`, 'ok')
      } catch {
        /* ApiError 已自动 toast */
      } finally {
        setAdapting(false)
        setStream({})
      }
    },
    [draft, selected],
  )

  /* ---------------------------------------------------------- 预检 */

  const runPrecheck = useCallback(async () => {
    if (!draft) return
    setChecking(true)
    try {
      const r = await publishApi.precheck(draft.id, selected)
      setPrecheck(r)
      return r
    } catch {
      return null
    } finally {
      setChecking(false)
    }
  }, [draft, selected])

  const autofix = async (platform: string, field: 'body' | 'title' | 'all') => {
    if (!draft) return
    try {
      const r = await publishApi.autofix(draft.id, platform as PlatformKey, field)
      setDraft(r.draft)
      toast(`已裁剪到 ${r.after}/${r.limit} 字，硬门禁解除`, 'ok')
      await runPrecheck()
    } catch {
      /* ApiError 已自动 toast */
    }
  }

  /* ---------------------------------------------------------- 发布 */

  const doPublish = async () => {
    if (!draft) return
    setPublishing(true)
    try {
      const r = await publishApi.publish(draft.id, selected)
      setRuns(r.results)
      if (r.draft) setDraft(r.draft)
      setRecords((await publishApi.records(draft.id)).records)
      const sms = r.results.find((x) => x.status === 'awaiting_sms')
      if (sms?.record_id) setSmsRecord(sms.record_id)
      if (r.failed_count > 0) toast(`${r.failed_count} 个平台发布失败，看下面状态卡的失败原因`, 'warn')
      else toast(r.notice || '已发布', 'ok')
      await runPrecheck()
    } catch (e) {
      // 硬门禁未解除 → 后端 422 GateBlocked，这里只提示不发
      const code = (e as { code?: string }).code
      if (code === 'GateBlocked') toast('硬门禁未解除：先修掉预检里的红 ✗ 项再发布', 'warn')
    } finally {
      setPublishing(false)
      setConfirmOpen(false)
    }
  }

  /**
   * 主按钮：**先跑预检**。有 BLOCK 未过时只 toast 并**不发**（UI-SPEC 规则 16/17）；
   * 后端的 422 GateBlocked 是第二道保险。
   */
  const onMainClick = async () => {
    if (selected.length === 0) {
      toast('先勾选至少一个平台', 'warn')
      return
    }
    const r = await runPrecheck()
    if (!r) return
    if (r.blocked) {
      toast(`硬门禁未解除：还有 ${r.block_count} 项必须先修（见右侧预检）`, 'warn')
      return
    }
    setConfirmOpen(true)
  }

  const retry = async (recordId: string) => {
    try {
      const r = await publishApi.retry(recordId)
      if (r.skipped) toast(r.message ?? '这条不需要重试', 'warn')
      else {
        setRuns(r.results)
        toast('已重试', 'ok')
      }
    } catch {
      /* ApiError 已自动 toast */
    }
  }

  /* ---------------------------------------------------------- 派生 */

  const variantOf = (p: PlatformKey) => {
    const v = draft?.variants.find((x) => x.platform === p)
    return v ?? {
      platform: p,
      title: draft?.title ?? '',
      body: draft?.body ?? '',
      char_count: 0,
      char_limit: 0,
      over_limit: false,
      adapted: false,
      status: 'pending' as const,
      error: null,
      published_url: null,
    }
  }

  const generated = useMemo(() => draft?.variants.filter((v) => v.adapted).length ?? 0, [draft])
  const selectedMeta = useMemo(
    () => platforms.filter((p) => selected.includes(p.platform)),
    [platforms, selected],
  )

  if (!booted) {
    return (
      <div className="view-pad stack" style={{ gap: 12 }}>
        <Skeleton height={22} width={220} />
        <Skeleton height={86} radius={14} />
      </div>
    )
  }

  return (
    <div className="view-pad">
      <PageHead
        title="发布中心"
        desc="一份母版，多平台适配。逐字流式生成 + 逐平台字数门禁。"
        actions={
          <>
            {scheduler && scheduler.enabled ? (
              <Chip tone="outline" title={scheduler.notice}>
                定时发布 · 每 {scheduler.interval_seconds}s 扫描 · {scheduler.due_count} 条到期
              </Chip>
            ) : null}
            {scheduler && scheduler.enabled === false ? (
              <Chip tone="warn" title={scheduler.notice}>
                定时发布已停用（ATELIER_SCHEDULER=0）
              </Chip>
            ) : null}
            <Chip tone="accent">
              <i className="live-dot" />
              {savedAt ? `草稿自动保存 · ${new Date(savedAt).toTimeString().slice(0, 5)}` : '草稿自动保存'}
            </Chip>
            <Button onClick={() => toast('排期发布属 M4 批次（adapter.schedule 已留签名）', 'warn')}>排期发布</Button>
            <Button
              variant="primary"
              loading={publishing}
              disabled={selected.length === 0}
              disabledReason={selected.length === 0 ? '先在下面勾选至少一个平台' : undefined}
              onClick={() => void onMainClick()}
            >
              {selected.length === 0 ? '先选平台' : `发布到 ${selected.length} 个平台`}
            </Button>
          </>
        }
      />

      <div className="pub">
        <div className="stack">
          {draft ? (
            <MasterEditor
              draft={draft}
              onSave={save}
              onRegen={() => void runAdapt()}
              savedAt={savedAt}
              adapting={adapting}
            />
          ) : (
            <div className="card card-b">
              <p className="help">还没有草稿。</p>
              <Button
                variant="primary"
                onClick={async () => {
                  const d = await publishApi.createDraft({ title: '', body: '' })
                  setDraft(d)
                }}
              >
                新建一份草稿
              </Button>
            </div>
          )}

          <PlatformPicker
            platforms={platforms}
            selected={selected}
            generated={generated}
            adapting={adapting}
            onToggle={toggle}
            extraActions={
              <Button
                size="sm"
                variant="ghost"
                icon={Wand2}
                disabled={!draft}
                disabledReason="先新建或选一份草稿"
                onClick={() => setOptimizeOpen(true)}
              >
                优化建议
              </Button>
            }
          >
            {selected.map((p) => (
              <PlatformVariantCard key={p} variant={variantOf(p)} streaming={stream[p]} />
            ))}
          </PlatformPicker>

          <MediaAttachments
            attachments={draft?.attachments ?? []}
            onRemove={(path) => {
              const next = (draft?.attachments ?? []).filter((x) => x !== path)
              patch({ attachments: next })
              void save({ attachments: next })
              void runPrecheck()
            }}
            onAdd={() => navigate('/library')}
            onGoLibrary={() => navigate('/library')}
          />
        </div>

        <div className="stack">
          <PrecheckPanel
            result={precheck}
            loading={checking}
            onAutofix={(p, f) => void autofix(p, f)}
            onGoAccounts={() => navigate('/accounts')}
            onGoLibrary={() => navigate('/library')}
            onRerun={() => void runPrecheck()}
          />

          <PublishStatusList
            runs={runs}
            records={records}
            pendingPlatforms={runs.length === 0 ? selectedMeta.map((p) => p.name) : []}
            onGoAccounts={() => navigate('/accounts')}
            onRetry={(id) => void retry(id)}
          />
        </div>
      </div>

      <PublishConfirmDialog
        open={confirmOpen}
        platforms={selectedMeta}
        busy={publishing}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => void doPublish()}
      />
      <OptimizeDialog
        open={optimizeOpen}
        onClose={() => setOptimizeOpen(false)}
        draft={draft}
        platforms={platforms}
        onReplaceTitle={replaceTitle}
      />
      <SmsDialog
        recordId={smsRecord}
        onClose={() => setSmsRecord(null)}
        onSubmitted={() => {
          setSmsRecord(null)
          if (draft) void publishApi.records(draft.id).then((r) => setRecords(r.records))
        }}
      />
    </div>
  )
}

export default PublishPage
