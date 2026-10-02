import { useCallback, useEffect, useState } from 'react'
import { ArrowRight, Check } from 'lucide-react'
import { Button, Chip, Input, Modal, ProgressBar, Textarea, toast } from '@/components'
import { profileApi } from './api'
import type { ProfileDetail, WizardProgress, WizardStepMeta } from './api'

export type ProfileWizardProps = {
  open: boolean
  /** 建完回调，把新画像交给页面渲染 */
  onDone: (profile: ProfileDetail) => void
  /** 中途放弃：保留已填内容（spec §5） */
  onAbandon: (profile: ProfileDetail) => void
  onClose: () => void
  created: { profile: ProfileDetail; token: string } | null
}

/** 4 步表单的本地草稿。第 1 步只有账号名是必填。 */
type Draft = Record<string, Record<string, string>>

const EMPTY: Draft = { basic: { name: '', platform: '', direction: '' }, social: { urls: '' }, intent: { goals: '' }, redlines: { bans: '' } }

const GOAL_OPTIONS = ['涨粉', '接商单', '做转化', '做个人品牌', '验证选题']

/**
 * 新建向导 4 步（spec §5 / §6）。
 *
 * 三条硬要求：
 * 1. **除第 1 步外每步都能「先跳过」，且跳过照样推进**——这是「全程 < 3 分钟」的关键。
 * 2. 第 1 步只要账号名就能完成。
 * 3. 顶部显示 ``2/4``，跳过时明确告诉用户「已跳过，随时能补」。
 */
export function ProfileWizard({ open, onDone, onAbandon, onClose, created }: ProfileWizardProps) {
  const [steps, setSteps] = useState<WizardStepMeta[]>([])
  const [cursor, setCursor] = useState(0)
  const [token, setToken] = useState('')
  const [progress, setProgress] = useState<WizardProgress | null>(null)
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const [busy, setBusy] = useState(false)

  // 每次打开都从后端取一次进度：中途退出再进来，接着上次走
  useEffect(() => {
    if (!open || !created) return
    let alive = true
    setDraft(EMPTY)
    setToken(created.token)
    setCursor(0)
    void profileApi
      .wizardGet(created.profile.id, created.token)
      .then((p) => {
        if (!alive) return
        setSteps(p.steps ?? [])
        setProgress(p)
        setCursor(Math.min(p.progress, p.steps.length - 1))
      })
      .catch(() => {
        /* 取不到就当从头走：后端在缺 token 时会自己补一个 */
      })
    return () => {
      alive = false
    }
  }, [open, created])

  const current = steps[cursor]

  const setField = useCallback((key: string, field: string, value: string) => {
    setDraft((d) => ({ ...d, [key]: { ...(d[key] ?? {}), [field]: value } }))
  }, [])

  const step = useCallback(
    async (skip: boolean) => {
      if (!created || !current || busy) return
      const data = draft[current.key] ?? {}
      const firstStep = cursor === 0
      // 第 1 步最少要账号名，前端先拦一道（后端也会再拦一次）
      if (firstStep && !skip && !data.name?.trim()) {
        toast.warn('先给账号起个名字，其他都可以跳过')
        return
      }
      setBusy(true)
      try {
        const next = await profileApi.wizardStep(created.profile.id, {
          step: current.key,
          data: skip ? {} : data,
          skip,
          token,
        })
        setProgress(next)
        setToken(next.token)
        if (skip && !firstStep) {
          toast.info(`已跳过「${current.title}」，随时能在六维编辑页补`)
        }
        if (next.next_step === 'done' || next.progress >= steps.length) {
          // 走完 4 步：直接收起向导，落到六维编辑页继续（不再挡一层确认）
          onDone(next.profile ?? (await profileApi.detail(created.profile.id)))
        } else {
          setCursor(Math.min(next.progress, steps.length - 1))
        }
      } finally {
        setBusy(false)
      }
    },
    [busy, created, current, cursor, draft, onDone, steps.length, token],
  )

  const finish = useCallback(async () => {
    if (!created || busy) return
    setBusy(true)
    try {
      const done = await profileApi.wizardStep(created.profile.id, { step: 'done', token })
      onDone(done.profile ?? (await profileApi.detail(created.profile.id)))
    } finally {
      setBusy(false)
    }
  }, [busy, created, onDone, token])

  const abandon = useCallback(async () => {
    if (!created || busy) return
    setBusy(true)
    try {
      const res = await profileApi.wizardAbandon(created.profile.id, token)
      onAbandon(res.profile ?? (await profileApi.detail(created.profile.id)))
    } finally {
      setBusy(false)
    }
  }, [busy, created, onAbandon, token])

  const doneCount = progress?.progress ?? 0
  const label = progress?.progress_label ?? `0/${steps.length || 4}`
  const canSkip = Boolean(current?.skippable) && !(cursor === 0)

  return (
    <Modal
      open={open}
      onClose={onClose}
      width={560}
      title={`第 ${current?.index ?? 1} 步 · ${current?.title ?? '基础信息'}`}
      sub={current?.sub ?? ''}
      footer={
        <>
          <Button variant="ghost" onClick={() => void abandon()}>
            中途放弃
          </Button>
          <span style={{ flex: 1 }} />
          {canSkip ? (
            <Button disabled={busy} onClick={() => void step(true)}>
              先跳过
            </Button>
          ) : null}
          <Button variant="primary" icon={doneCount >= 3 ? Check : ArrowRight} loading={busy} onClick={() => void step(false)}>
            {doneCount >= 3 ? '完成' : '下一步'}
          </Button>
        </>
      }
    >
      <div style={{ marginBottom: 14 }}>
        <div className="row" style={{ gap: 8, marginBottom: 6 }}>
          <span className="lbl">进度</span>
          <Chip tone="accent" mono>
            {label}
          </Chip>
          <span className="help" style={{ marginLeft: 'auto' }}>
            {progress?.skipped?.length ? `已跳过 ${progress.skipped.length} 步` : '跳过也能走完，全程 3 分钟内'}
          </span>
        </div>
        <ProgressBar value={(doneCount / (steps.length || 4)) * 100} label="向导进度" />
      </div>

      {!current ? null : (
        <div className="stack" style={{ gap: 12 }}>
          {current.key === 'basic' ? (
            <>
              <Input
                label="账号名（必填）"
                placeholder="例：AI 效率观察"
                value={draft.basic?.name ?? ''}
                onChange={(e) => setField('basic', 'name', e.target.value)}
              />
              <Input
                label="主平台"
                placeholder="小红书 / 抖音 / 公众号"
                value={draft.basic?.platform ?? ''}
                onChange={(e) => setField('basic', 'platform', e.target.value)}
              />
              <Textarea
                label="内容方向"
                placeholder="一句话说清你主要写什么"
                rows={2}
                help="这两个都可以留空，以后在「定位」里补"
                value={draft.basic?.direction ?? ''}
                onChange={(e) => setField('basic', 'direction', e.target.value)}
              />
            </>
          ) : null}

          {current.key === 'social' ? (
            <Textarea
              label="各平台主页链接"
              placeholder={'小红书 https://xhslink.com/xxx\n抖音 https://v.douyin.com/xxx'}
              rows={4}
              mono
              help={current.hint}
              value={draft.social?.urls ?? ''}
              onChange={(e) => setField('social', 'urls', e.target.value)}
            />
          ) : null}

          {current.key === 'intent' ? (
            <div className="field">
              <label>这个号想达成什么（可多选）</label>
              <div className="row" style={{ gap: 7, flexWrap: 'wrap' }}>
                {GOAL_OPTIONS.map((g) => {
                  const on = (draft.intent?.goals ?? '').includes(g)
                  return (
                    <Chip
                      key={g}
                      tone={on ? 'accent' : 'outline'}
                      onClick={() => {
                        const cur = (draft.intent?.goals ?? '').split('、').filter(Boolean)
                        const next = on ? cur.filter((x) => x !== g) : [...cur, g]
                        setField('intent', 'goals', next.join('、'))
                      }}
                    >
                      {g}
                    </Chip>
                  )
                })}
              </div>
              <span className="help">{current.hint}</span>
            </div>
          ) : null}

          {current.key === 'redlines' ? (
            <Textarea
              label="不想出现的话 / 禁忌话题"
              placeholder={'一行一条，例如：\n不写「震惊 / 必看 / 绝了」\n不做未实测的产品对比'}
              rows={4}
              help={current.hint}
              value={draft.redlines?.bans ?? ''}
              onChange={(e) => setField('redlines', 'bans', e.target.value)}
            />
          ) : null}
        </div>
      )}

      {current ? (
        <div className="row" style={{ marginTop: 12, gap: 8 }}>
          <span className="help">{current.hint}</span>
          {canSkip ? (
            <span className="help" style={{ marginLeft: 'auto' }}>
              也可以直接
              <button type="button" className="btn ghost sm" style={{ marginLeft: 4 }} onClick={() => void finish()}>
                结束向导
              </button>
            </span>
          ) : null}
        </div>
      ) : null}
    </Modal>
  )
}

export default ProfileWizard
