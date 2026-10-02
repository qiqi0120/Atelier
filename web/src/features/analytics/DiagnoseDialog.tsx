/** SPEC-11 §4 · F-E13 账号诊断弹层：诚实模式——记录不足不调模型，出「数据不足」空态。
 *
 * findings 的状态色只用于状态（good=accent / warn=琥珀 / bad=红，UI-SPEC §2）；
 * 限流信号 / 流量池阶段固定 notice 如实标注依赖 M5 数据回收。
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Chip, EmptyState, Modal } from '@/components'
import { useAtelier } from '@/lib/store'
import { describeError } from '@/lib/gates'
import { analyticsApi } from './api'
import { FINDING_LABEL, FINDING_TONE, type DiagnoseResponse } from './types'

export type DiagnoseDialogProps = {
  open: boolean
  onClose: () => void
}

export function DiagnoseDialog({ open, onClose }: DiagnoseDialogProps) {
  const navigate = useNavigate()
  const profile = useAtelier((s) => s.profile)
  const profileId = profile && !profile.generalMode ? profile.id : undefined

  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<DiagnoseResponse | null>(null)
  const [errorText, setErrorText] = useState('')

  const close = () => {
    setResult(null)
    setErrorText('')
    onClose()
  }

  const run = async () => {
    setRunning(true)
    setErrorText('')
    try {
      setResult(await analyticsApi.diagnose(profileId))
    } catch (e) {
      setErrorText(describeError(e))
    } finally {
      setRunning(false)
    }
  }

  const insufficient = result?.insufficient === true

  return (
    <Modal
      open={open}
      onClose={close}
      title="账号诊断"
      sub="基于本地发布记录与选题流转给诊断结论——数据不足时如实说，不编分数"
      width={600}
      footer={
        result ? (
          <Button variant="primary" onClick={close}>
            完成
          </Button>
        ) : (
          <>
            <Button onClick={close}>取消</Button>
            <Button variant="primary" loading={running} onClick={() => void run()}>
              开始诊断
            </Button>
          </>
        )
      }
    >
      {result && insufficient ? (
        <div className="stack" style={{ gap: 10 }}>
          <EmptyState
            title={`发布满 ${result.need} 条后才有诊断`}
            description={result.message}
            actionLabel="去发布中心发一条"
            onAction={() => {
              close()
              navigate('/publish')
            }}
          />
          <p style={{ margin: 0, fontSize: 12.5, color: 'var(--ink-3)' }}>
            当前记录：{result.stats.records_total} 条
            {Object.entries(result.stats.by_platform).length > 0
              ? `（${Object.entries(result.stats.by_platform).map(([p, n]) => `${p} ${n} 条`).join('、')}）`
              : ''}
            ，草稿 {result.stats.drafts_total} 份，选题待做 {result.stats.topics_flow.todo} 条。
          </p>
        </div>
      ) : null}
      {result && !insufficient ? (
        <div className="stack" style={{ gap: 12 }}>
          <p className="sysfile warn" style={{ margin: 0 }}>
            {result.notice}
          </p>
          <div className="stack" style={{ gap: 8 }}>
            {result.findings.map((f) => (
              <div key={f.dimension} className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
                <Chip tone={FINDING_TONE[f.status]}>{FINDING_LABEL[f.status]}</Chip>
                <div style={{ flex: 1, fontSize: 13 }}>
                  <b>{f.dimension}</b>
                  <span style={{ color: 'var(--ink-2)' }}> — {f.note}</span>
                </div>
              </div>
            ))}
          </div>
          <div>
            <p style={{ margin: '0 0 6px', fontSize: 12.5, fontWeight: 600, color: 'var(--ink-2)' }}>
              下一步建议
            </p>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
              {result.advice.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
      {!result ? (
        <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-2)' }}>
          诊断四个维度：垂直度、定位清晰度、更新节奏、平台覆盖。数据全部来自本地真实记录，
          AI 只做解读；发布记录不足 5 条时会明确提示而不是给假分数。
        </p>
      ) : null}
      {errorText ? (
        <p className="sysfile danger" style={{ whiteSpace: 'pre-line' }} role="alert">
          {errorText}
        </p>
      ) : null}
    </Modal>
  )
}

export default DiagnoseDialog
