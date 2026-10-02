/** SPEC-12 §3 · 策划域 P3 三弹层（F-E15 营销策划 / F-E16 直播策划 / F-E17 商单）。
 *
 * 与 StrategyDialog 同构（running/result/errorText 三态），按 kind 参数化，
 * 输出都是 5 段 markdown、不落库、缺段 422 展示改法。
 */

import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button, Field, Input, Modal, Textarea } from '@/components'
import { useAtelier } from '@/lib/store'
import { describeError } from '@/lib/gates'
import { analyticsPlanApi, type PlanKind } from './api'
import type { StrategyResult } from './types'

const PLAN_META: Record<PlanKind, { title: string; sub: string; intro: string; ok: string }> = {
  campaign: {
    title: '营销活动策划',
    sub: '节日 / 电商大促 / 新品发布的完整方案',
    intro: '生成五段式方案：活动目标、主题创意、节奏排期、渠道分工、预算与 KPI。不落库，满意后自行摘取。',
    ok: '生成方案',
  },
  liveplan: {
    title: '直播策划',
    sub: '直播流程 / 话术 / 互动设计',
    intro: '生成五段式方案：直播目标、流程脚本、话术要点、互动设计、风险预案。不落库。',
    ok: '生成方案',
  },
  sponsorship: {
    title: '品牌合作方案',
    sub: '商单 / 联名策划提案',
    intro: '把品牌方需求原文贴进来，生成五段式提案：合作解读、创意方案、内容形式、报价建议、风险与边界。报价是估算逻辑并如实标注。',
    ok: '生成提案',
  },
}

export type PlanDialogProps = {
  open: boolean
  kind: PlanKind
  onClose: () => void
}

export function PlanDialog({ open, kind, onClose }: PlanDialogProps) {
  const profile = useAtelier((s) => s.profile)
  const profileId = profile && !profile.generalMode ? profile.id : undefined
  const meta = PLAN_META[kind]

  const [primary, setPrimary] = useState('')
  const [secondary, setSecondary] = useState('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<StrategyResult | null>(null)
  const [errorText, setErrorText] = useState('')

  useEffect(() => {
    if (open) {
      setPrimary('')
      setSecondary('')
      setResult(null)
      setErrorText('')
    }
  }, [open])

  const close = () => {
    setResult(null)
    setErrorText('')
    onClose()
  }

  const run = async () => {
    setRunning(true)
    setErrorText('')
    try {
      const r =
        kind === 'campaign'
          ? await analyticsPlanApi.campaign(primary, secondary, profileId)
          : kind === 'liveplan'
            ? await analyticsPlanApi.liveplan(primary, secondary, profileId)
            : await analyticsPlanApi.sponsorship(primary, secondary, profileId)
      setResult(r)
    } catch (e) {
      setErrorText(describeError(e))
    } finally {
      setRunning(false)
    }
  }

  const primaryLabel = kind === 'campaign' ? '活动主题' : kind === 'liveplan' ? '直播主题' : '品牌需求原文'
  const secondaryLabel = kind === 'campaign' ? '场景（可选）' : kind === 'liveplan' ? '时长（可选）' : '品牌名（可选）'

  return (
    <Modal
      open={open}
      onClose={close}
      title={meta.title}
      sub={profileId ? `基于画像「${profile?.name}」生成` : '通用模式（未绑定画像），结果会如实标注'}
      width={640}
      footer={
        result ? (
          <Button variant="primary" onClick={close}>
            完成
          </Button>
        ) : (
          <>
            <Button onClick={close}>取消</Button>
            <Button
              variant="primary"
              loading={running}
              disabled={!primary.trim()}
              onClick={() => void run()}
            >
              {meta.ok}
            </Button>
          </>
        )
      }
    >
      {result ? (
        <div className="md" style={{ fontSize: 13.5, maxHeight: '58vh', overflow: 'auto' }}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.markdown}</ReactMarkdown>
        </div>
      ) : (
        <div className="stack" style={{ gap: 10 }}>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-2)' }}>{meta.intro}</p>
          {kind === 'sponsorship' ? (
            <Field label={primaryLabel} required help="至少 10 字：合作什么、投什么平台、预期效果">
              {(id) => (
                <Textarea id={id} value={primary} onChange={(e) => setPrimary(e.target.value)} />
              )}
            </Field>
          ) : (
            <Field label={primaryLabel} required>
              {(id) => <Input id={id} value={primary} onChange={(e) => setPrimary(e.target.value)} />}
            </Field>
          )}
          <Field label={secondaryLabel}>
            {(id) => <Input id={id} value={secondary} onChange={(e) => setSecondary(e.target.value)} />}
          </Field>
        </div>
      )}
      {errorText ? (
        <p className="sysfile danger" style={{ whiteSpace: 'pre-line' }} role="alert">
          {errorText}
        </p>
      ) : null}
    </Modal>
  )
}

export default PlanDialog
