/** SPEC-04 §5 · 技能库页（照 design/prototype-v1.html 的 `#v-skills`）。
 *
 * 数据全部来自 GET /api/skills（skills/ 目录是唯一事实源），页面不再内置目录。
 * 行为要点：
 * - F-C7 详情抽屉：GET /api/skills/{id} → SKILL.md 全文 + 参数表单 + 运行历史
 * - F-C8 就地运行：POST /run → 异步轮询 run（1.5s / 上限 120s）；付费技能先
 *   弹费用确认（cost_pending），确认后带 confirm_cost 重发（PRD 原则三）
 * - F-C10 缺钥禁用：runnable=false → 运行按钮 disabled + 原因，卡片带 ! 角标
 * - F-C9 密钥配置：抽屉内按 required_keys 渲染掩码输入，留空不提交（POST /api/keys）
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Blocks,
  ChartLine,
  Flame,
  Hammer,
  KeyRound,
  Save,
  Search,
  Send,
  Shield,
  SlidersHorizontal,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Badge, Button, Chip, Drawer, EmptyState, Field, Input, Modal, Skeleton, toast } from '@/components'
import { MATURITY_LABEL } from '@/lib/types'
import type { SkillBrief, SkillDetail, SkillLayer, SkillRun, SkillRunResponse } from '@/lib/types'
import { ApiError } from '@/lib/api'
import { describeError } from '@/lib/gates'
import { useAtelier } from '@/lib/store'
import { PageHead } from '@/features/shared/PageHead'
import { skillsApi } from './api'

const LAYER_ICON: Record<SkillLayer, LucideIcon> = {
  发现: Flame,
  策划: Search,
  制作: Hammer,
  发布: Send,
  归因: ChartLine,
  通用: Blocks,
}

const RUN_STATUS_LABEL: Record<string, string> = {
  running: '运行中',
  done: '完成',
  failed: '失败',
  cost_pending: '待确认费用',
}

/** 轮询节奏：1.5s 一次，最长 120s（ffmpeg 类技能可能要跑几十秒） */
const POLL_MS = 1500
const POLL_MAX_MS = 120_000

const lockedReason = (s: SkillBrief) => `缺少 ${s.missing_keys.join('、')}，运行已禁用`

const fmtTime = (iso?: string) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}

const firstLine = (md: string) => md.split('\n').find((l) => l.trim()) ?? ''

export function SkillsPage() {
  const navigate = useNavigate()
  const profile = useAtelier((s) => s.profile)
  const profileId = profile && !profile.generalMode ? profile.id : undefined

  // ---- 列表 ----
  const [skills, setSkills] = useState<SkillBrief[]>([])
  const [count, setCount] = useState(0)
  const [layers, setLayers] = useState<SkillLayer[]>([])
  const [loading, setLoading] = useState(true)
  const [errorText, setErrorText] = useState('')
  const [q, setQ] = useState('')
  const [layer, setLayer] = useState('all')

  const loadList = useCallback(async () => {
    setLoading(true)
    setErrorText('')
    try {
      const r = await skillsApi.list()
      setSkills(r.skills)
      setCount(r.count)
      setLayers(r.layers)
    } catch (e) {
      // api 层已 toast，这里只落状态条
      setErrorText(describeError(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadList()
  }, [loadList])

  // ---- 详情抽屉 ----
  const [openId, setOpenId] = useState<string | null>(null)
  const [detail, setDetail] = useState<SkillDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [history, setHistory] = useState<SkillRun[]>([])
  const [paramValues, setParamValues] = useState<Record<string, string>>({})
  const [keyValues, setKeyValues] = useState<Record<string, string>>({})
  const [keySaving, setKeySaving] = useState(false)

  // ---- 运行 ----
  const [running, setRunning] = useState(false)
  const [runResult, setRunResult] = useState<SkillRun | null>(null)
  const [runError, setRunError] = useState('')
  const [runTimeout, setRunTimeout] = useState(false)
  const [costPending, setCostPending] = useState<SkillRunResponse | null>(null)
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  /** 当前抽屉打开的技能 id（loadHistory 回写时校验，防止串台） */
  const openIdRef = useRef<string | null>(null)

  const stopPolling = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current)
      pollTimer.current = null
    }
  }, [])

  useEffect(() => stopPolling, [stopPolling])

  const loadHistory = useCallback(async (skillId: string) => {
    try {
      const r = await skillsApi.history(skillId, 5)
      if (openIdRef.current === skillId) setHistory(r.runs)
    } catch {
      if (openIdRef.current === skillId) setHistory([])
    }
  }, [])

  const openSkill = useCallback(
    async (id: string) => {
      stopPolling()
      openIdRef.current = id
      setOpenId(id)
      setDetail(null)
      setDetailError('')
      setRunResult(null)
      setRunError('')
      setRunTimeout(false)
      setCostPending(null)
      setHistory([])
      setParamValues({})
      setKeyValues({})
      setDetailLoading(true)
      try {
        const d = await skillsApi.detail(id)
        setDetail(d)
        setParamValues(Object.fromEntries(d.params.map((p) => [p.key, p.default])))
        void loadHistory(id)
      } catch (e) {
        setDetailError(describeError(e))
      } finally {
        setDetailLoading(false)
      }
    },
    [loadHistory, stopPolling],
  )

  const closeDrawer = useCallback(() => {
    stopPolling()
    openIdRef.current = null
    setOpenId(null)
    setCostPending(null)
  }, [stopPolling])

  /** 运行结束（done/failed 终态）统一收口 */
  const finishRun = useCallback(
    (r: SkillRun) => {
      stopPolling()
      setRunning(false)
      setRunResult(r)
      if (r.status === 'done') {
        toast(`运行完成，产物已写入 outputs/<项目>/（${Number(r.duration ?? 0).toFixed(1)}s）`, 'ok')
        void loadHistory(r.skill_id)
      }
    },
    [loadHistory, stopPolling],
  )

  const startPolling = useCallback(
    (runId: string) => {
      stopPolling()
      setRunning(true)
      const startedAt = Date.now()
      const tick = async () => {
        try {
          const r = await skillsApi.runStatus(runId)
          if (r.status !== 'running') {
            finishRun(r)
            return
          }
        } catch {
          // 单次状态查询失败不打断：长任务期间网络抖动，重试到 120s 上限为止
        }
        if (Date.now() - startedAt >= POLL_MAX_MS) {
          stopPolling()
          setRunning(false)
          setRunTimeout(true)
        }
      }
      pollTimer.current = setInterval(() => void tick(), POLL_MS)
      void tick()
    },
    [finishRun, stopPolling],
  )

  const runSkill = useCallback(
    async (confirmCost: boolean) => {
      if (!detail) return
      setRunError('')
      setRunTimeout(false)
      setRunResult(null)
      setRunning(true)
      try {
        const res = await skillsApi.run(detail.id, {
          params: paramValues,
          project: 'default',
          profile_id: profileId,
          confirm_cost: confirmCost,
        })
        if (res.status === 'cost_pending') {
          // 付费技能：先给费用预估，用户确认后才真正执行（PRD 原则三）
          setRunning(false)
          setCostPending(res)
          return
        }
        if (res.status === 'running' && res.run_id) {
          startPolling(res.run_id)
          return
        }
        finishRun(res)
      } catch (e) {
        setRunning(false)
        setRunError(describeError(e))
      }
    },
    [detail, finishRun, paramValues, profileId, startPolling],
  )

  const saveKeys = useCallback(async () => {
    if (!detail) return
    const filled = detail.required_keys.filter((k) => (keyValues[k] ?? '').trim())
    if (!filled.length) {
      toast('没有要保存的密钥：留空即保持已存值不变', 'warn')
      return
    }
    setKeySaving(true)
    try {
      for (const k of filled) await skillsApi.saveKey(k, keyValues[k].trim())
      toast('密钥已保存，运行状态已刷新', 'ok')
      setKeyValues({})
      try {
        const d = await skillsApi.detail(detail.id)
        setDetail(d)
      } catch (e) {
        setDetailError(describeError(e))
      }
      void loadList()
    } catch {
      // api 层已 toast
    } finally {
      setKeySaving(false)
    }
  }, [detail, keyValues, loadList])

  // ---- 过滤 ----
  const list = useMemo(() => {
    const kw = q.trim().toLowerCase()
    return skills.filter((s) => {
      if (layer !== 'all' && s.layer !== layer) return false
      if (kw && !(`${s.name}${s.trigger}`.toLowerCase().includes(kw))) return false
      return true
    })
  }, [skills, q, layer])

  const tabItems = useMemo(
    () => [
      { key: 'all', label: '全部', count },
      ...layers.map((l) => ({ key: l as string, label: l as string, count: skills.filter((s) => s.layer === l).length })),
    ],
    [count, layers, skills],
  )

  const grouped = useMemo(
    () =>
      layers
        .map((l) => ({ layer: l, items: list.filter((s) => s.layer === l) }))
        .filter((g) => g.items.length > 0),
    [layers, list],
  )

  const locked = Boolean(detail && !detail.runnable)
  const runFailedText = runResult?.status === 'failed' ? describeError(new ApiError(
    runResult.error?.code ?? 'SkillRunFailed',
    0,
    runResult.error?.message ?? '技能运行失败',
    undefined,
    runResult.error?.hint ?? undefined,
  )) : ''

  return (
    <div className="view-pad">
      <PageHead
        title="技能库"
        desc={
          <>
            进阶入口：单个技能的完整说明、就地运行、密钥配置。带{' '}
            <Badge tone="warn" style={{ verticalAlign: '1px' }}>
              !
            </Badge>{' '}
            的表示缺配置。
          </>
        }
        actions={
          <>
            <Input
              sizeSm
              placeholder="搜索技能 / 触发语…"
              value={q}
              style={{ width: 190 }}
              onChange={(e) => setQ(e.target.value)}
              aria-label="搜索技能"
            />
            <Button icon={SlidersHorizontal} onClick={() => navigate('/settings')}>
              批量配置密钥
            </Button>
          </>
        }
      />

      {errorText ? (
        <div className="card card-b" style={{ marginBottom: 14 }}>
          <p className="sysfile danger" role="alert">
            {errorText}
          </p>
          <Button style={{ marginTop: 10 }} onClick={() => void loadList()}>
            重试
          </Button>
        </div>
      ) : null}

      {!errorText && skills.length > 0 ? (
        <div className="tabs" style={{ marginBottom: 18 }} role="tablist" aria-label="技能层">
          {tabItems.map((t) => (
            <button
              type="button"
              key={t.key}
              role="tab"
              aria-selected={layer === t.key}
              className={`tab ${layer === t.key ? 'on' : ''}`}
              onClick={() => setLayer(t.key)}
            >
              {t.label} <span className="mut2">{t.count}</span>
            </button>
          ))}
        </div>
      ) : null}

      {loading ? (
        <div className="sk-grid" aria-busy>
          {Array.from({ length: 6 }, (_, i) => (
            <div className="sk" key={i} aria-hidden>
              <Skeleton height={15} width="55%" />
              <Skeleton height={12} width="90%" />
              <Skeleton height={12} width="70%" />
            </div>
          ))}
        </div>
      ) : skills.length === 0 ? (
        <EmptyState
          title="技能库还是空的"
          description="skills/ 目录下还没有 SKILL.md。放一个技能目录（含 SKILL.md）进来，或先去能力地图看看对话能力。"
          actionLabel="重新加载"
          onAction={() => void loadList()}
        />
      ) : list.length === 0 ? (
        <EmptyState
          title={`没有匹配「${q}」的技能`}
          description="试试搜「字幕」「发布」，或切到别的层。"
          actionLabel="清空筛选"
          onAction={() => {
            setQ('')
            setLayer('all')
          }}
        />
      ) : (
        grouped.map((g) => {
          const LayerIcon = LAYER_ICON[g.layer] ?? Blocks
          return (
            <div className="cap-grp" key={g.layer}>
              <div className="cap-grp-h">
                <h3>
                  <LayerIcon size={13} style={{ verticalAlign: '-2px', marginRight: 5 }} aria-hidden />
                  {g.layer}层技能
                </h3>
                <span className="mut" style={{ fontSize: 'var(--fs-sub)' }}>
                  {g.items.length} 个
                </span>
                <div className="sp">
                  <Chip tone="outline">{g.items.filter((s) => s.maturity === 'v0').length} 个已验证</Chip>
                </div>
              </div>
              <div className="sk-grid">
                {g.items.map((s) => {
                  const isLocked = !s.runnable
                  const Icon = LAYER_ICON[s.layer] ?? Blocks
                  return (
                    <div className={`sk ${isLocked ? 'locked' : ''}`} key={s.id}>
                      {isLocked ? (
                        <>
                          <Badge tone="warn" lg style={{ position: 'absolute', top: -6, right: -6 }}>
                            !
                          </Badge>
                          <span className="tool-tip">{lockedReason(s)}</span>
                        </>
                      ) : null}
                      <div className="top">
                        <span
                          className="ci"
                          style={{
                            width: 26,
                            height: 26,
                            borderRadius: 8,
                            background: 'var(--surface-2)',
                            color: 'var(--ink-2)',
                            display: 'grid',
                            placeItems: 'center',
                          }}
                        >
                          <Icon size={14} strokeWidth={1.9} />
                        </span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <h4>{s.name}</h4>
                          <span className={`mature ${s.maturity}`} style={{ marginTop: 3, display: 'inline-block' }}>
                            {MATURITY_LABEL[s.maturity]}
                          </span>
                        </div>
                      </div>
                      <p>{s.trigger}</p>
                      <div className="foot">
                        <Chip tone="outline" mono xs>
                          {s.cost}
                        </Chip>
                        <Button size="sm" style={{ marginLeft: 'auto' }} onClick={() => void openSkill(s.id)}>
                          详情 / 运行
                        </Button>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })
      )}

      {!loading && !errorText && skills.length > 0 ? (
        <div className="card card-b" style={{ marginTop: 6, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="mut" style={{ fontSize: 'var(--fs-sub)' }}>
            技能库共 {count} 个技能 · {layers.join(' / ')}
          </span>
          <Chip tone="outline" mono className="sp" style={{ marginLeft: 'auto' }}>
            skills/ · 每个技能一个 SKILL.md
          </Chip>
        </div>
      ) : null}

      <Drawer
        open={Boolean(openId)}
        onClose={closeDrawer}
        title={detail?.name ?? openId ?? ''}
        meta={
          detail ? (
            <>
              <span className={`mature ${detail.maturity}`}>{MATURITY_LABEL[detail.maturity]}</span>
              <Chip tone="outline" mono>
                skill/{detail.id}
              </Chip>
              <Chip tone="outline">{detail.layer}层</Chip>
              <Chip tone="outline" mono>
                {detail.cost}
              </Chip>
            </>
          ) : null
        }
        footer={
          openId ? (
            <>
              <span className="help" style={{ flex: 1 }}>
                就地运行会写入 <code className="mono">outputs/&lt;项目&gt;/</code>
              </span>
              <Button onClick={closeDrawer}>关闭</Button>
              <Button
                variant="primary"
                loading={running}
                disabled={locked || detailLoading || Boolean(detailError)}
                disabledReason={locked ? (detail?.block_reason ?? '缺少必需密钥') : undefined}
                onClick={() => void runSkill(false)}
              >
                {running ? '运行中…' : '运行'}
              </Button>
            </>
          ) : null
        }
      >
        {detailLoading ? (
          <div className="stack" style={{ gap: 10 }} aria-busy>
            <Skeleton height={18} width="45%" />
            <Skeleton height={12} />
            <Skeleton height={12} width="88%" />
            <Skeleton height={12} width="72%" />
          </div>
        ) : detailError ? (
          <div>
            <p className="sysfile danger" role="alert">
              {detailError}
            </p>
            <Button style={{ marginTop: 10 }} onClick={() => openId && void openSkill(openId)}>
              重试
            </Button>
          </div>
        ) : detail ? (
          <>
            <div className="md">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{detail.body_markdown}</ReactMarkdown>
            </div>

            {runError ? (
              <p className="sysfile danger" role="alert" style={{ marginTop: 12, whiteSpace: 'pre-wrap' }}>
                {runError}
              </p>
            ) : null}

            {detail.params.length ? (
              <>
                <div className="hr" />
                <div className="lbl" style={{ marginBottom: 9 }}>
                  运行参数
                </div>
                {detail.params.map((p) => (
                  <Field label={p.label} key={p.key}>
                    {(id) => (
                      <Input
                        id={id}
                        value={paramValues[p.key] ?? p.default}
                        onChange={(e) => setParamValues((v) => ({ ...v, [p.key]: e.target.value }))}
                      />
                    )}
                  </Field>
                ))}
              </>
            ) : null}

            {detail.required_keys.length ? (
              <>
                <div className="hr" />
                <div className="lbl" style={{ marginBottom: 9 }}>
                  API 配置
                </div>
                {locked ? (
                  <p className="sysfile" style={{ marginBottom: 10 }}>
                    <Shield size={12} style={{ verticalAlign: '-2px', marginRight: 4 }} aria-hidden />
                    {detail.block_reason}
                  </p>
                ) : null}
                {detail.required_keys.map((k) => (
                  <Field
                    label={k}
                    key={k}
                    help={
                      detail.missing_keys.includes(k) ? (
                        <b style={{ color: 'var(--warn-ink)' }}>当前未配置</b>
                      ) : (
                        '已配置。留空保存不会覆盖已存值（密钥只写不回传）。'
                      )
                    }
                  >
                    {(id) => (
                      <Input
                        id={id}
                        mono
                        revealable
                        autoComplete="off"
                        placeholder={detail.missing_keys.includes(k) ? '未配置 · 填写后可运行' : '已配置 · 留空不覆盖'}
                        value={keyValues[k] ?? ''}
                        onChange={(e) => setKeyValues((v) => ({ ...v, [k]: e.target.value }))}
                      />
                    )}
                  </Field>
                ))}
                <Button icon={Save} loading={keySaving} onClick={() => void saveKeys()} style={{ marginTop: 2 }}>
                  保存密钥
                </Button>
              </>
            ) : null}

            <div className="hr" />
            <div className="lbl" style={{ marginBottom: 9 }}>
              运行历史
            </div>
            {history.length === 0 ? (
              <p className="mut" style={{ fontSize: 'var(--fs-sub)' }}>
                还没跑过。运行记录落库，重启后仍可回查。
              </p>
            ) : (
              <div className="stack" style={{ gap: 6 }}>
                {history.map((r) => (
                  <div className="row" key={r.run_id} style={{ gap: 8, alignItems: 'center' }}>
                    <Chip tone={r.status === 'done' ? 'accent' : r.status === 'failed' ? 'danger' : 'warn'} xs>
                      {RUN_STATUS_LABEL[r.status] ?? r.status}
                    </Chip>
                    <span className="mut" style={{ fontSize: 11.5 }}>
                      {fmtTime(r.created_at)} · {Number(r.duration ?? 0).toFixed(1)}s
                    </span>
                    <span
                      className="mut"
                      style={{ fontSize: 11.5, marginLeft: 'auto', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={firstLine(r.result_markdown) || r.error?.message || ''}
                    >
                      {firstLine(r.result_markdown) || r.error?.message || '—'}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {running ? (
              <>
                <div className="hr" />
                <div className="stack" style={{ gap: 8 }} aria-busy>
                  <Skeleton height={14} width="40%" />
                  <p className="help">
                    正在运行。长任务（视频合成 / ffmpeg）可能要跑几十秒，先别关抽屉。
                  </p>
                </div>
              </>
            ) : runTimeout ? (
              <>
                <div className="hr" />
                <p className="sysfile">仍在运行，稍后可在运行历史查看。</p>
              </>
            ) : runResult ? (
              <>
                <div className="hr" />
                <div className="lbl" style={{ marginBottom: 9 }}>
                  运行结果
                </div>
                {runResult.status === 'failed' ? (
                  <p className="sysfile danger" role="alert" style={{ whiteSpace: 'pre-wrap' }}>
                    {runFailedText}
                  </p>
                ) : (
                  <>
                    <div className="md">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{runResult.result_markdown}</ReactMarkdown>
                    </div>
                    {runResult.cost_actual ? (
                      <p className="mut" style={{ fontSize: 'var(--fs-sub)', marginTop: 6 }}>
                        实际费用：¥{Number(runResult.cost_actual).toFixed(2)}
                      </p>
                    ) : null}
                    {runResult.artifacts.length ? (
                      <div className="stack" style={{ gap: 6, marginTop: 10 }}>
                        <div className="lbl">产物</div>
                        {runResult.artifacts.map((a) => (
                          <div className="row" key={a.path} style={{ gap: 8, alignItems: 'center' }}>
                            <Chip tone="outline" xs>
                              {a.kind}
                            </Chip>
                            <span style={{ fontSize: 12.5 }}>{a.name}</span>
                            <span
                              className="mut mono"
                              style={{ fontSize: 11.5, marginLeft: 'auto', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                              title={a.path}
                            >
                              {a.path}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </>
                )}
              </>
            ) : null}
          </>
        ) : null}
      </Drawer>

      <Modal
        open={Boolean(costPending)}
        onClose={() => setCostPending(null)}
        title={`运行「${detail?.name}」会产生费用`}
        sub="付费操作：先看清楚预估，确认后才执行。点「取消」不产生任何费用。"
        okText="我知道代价，继续"
        onOk={() => {
          setCostPending(null)
          void runSkill(true)
        }}
      >
        {costPending?.cost_estimate ? (
          <>
            <div className="precheck">
              <div className="s w">
                <KeyRound size={10} />
              </div>
              <div>
                <b>
                  约 {costPending.cost_estimate.currency === 'CNY' ? '¥' : ''}
                  {Number(costPending.cost_estimate.amount).toFixed(2)}
                </b>
                <span>
                  {costPending.cost_estimate.breakdown
                    .map((l) => `${l.label} ¥${Number(l.amount).toFixed(2)}`)
                    .join(' · ')}
                </span>
              </div>
            </div>
            {costPending.result_markdown ? (
              <div className="md" style={{ marginTop: 8 }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{costPending.result_markdown}</ReactMarkdown>
              </div>
            ) : null}
          </>
        ) : null}
      </Modal>
    </div>
  )
}

export default SkillsPage
