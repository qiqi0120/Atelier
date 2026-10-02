/** SPEC-08 §6 · F-E9 选题评分弹层：7 维打分 + 确定性结论（阈值由后端代码持有）。 */

import { useCallback, useEffect, useState } from 'react'
import { Button, Chip, Modal, toast } from '@/components'
import { useAtelier } from '@/lib/store'
import { topicsApi } from './api'
import { describeError } from '@/lib/gates'
import { DIM_ROWS, VERDICT_META, type Topic, type TopicScore } from './types'

export type ScoreDialogProps = {
  open: boolean
  topic: Topic | null
  onClose: () => void
}

export function ScoreDialog({ open, topic, onClose }: ScoreDialogProps) {
  const { profile } = useAtelier()
  const profileId = profile && !profile.generalMode ? profile.id : undefined

  const [score, setScore] = useState<Omit<TopicScore, 'title'> | null>(null)
  const [running, setRunning] = useState(false)
  const [errorText, setErrorText] = useState('')

  const loadPrev = useCallback(async (topicId: string) => {
    try {
      const r = await topicsApi.detail(topicId)
      setScore(r.score ?? null)
    } catch {
      setScore(null) // 历史分读不到不拦着重新评
    }
  }, [])

  useEffect(() => {
    if (open && topic) {
      setScore(null)
      setErrorText('')
      void loadPrev(topic.id)
    }
  }, [open, topic, loadPrev])

  const close = () => {
    setErrorText('')
    onClose()
  }

  const run = async () => {
    if (!topic) return
    setRunning(true)
    setErrorText('')
    try {
      setScore(await topicsApi.score(topic.id, profileId))
      toast.ok('评分完成，历史已保留')
    } catch (e) {
      setErrorText(describeError(e))
    } finally {
      setRunning(false)
    }
  }

  const verdict = score ? VERDICT_META[score.verdict] : null

  return (
    <Modal
      open={open}
      onClose={close}
      title="选题评分"
      sub={topic ? `「${topic.title}」按 7 维打分，结论由分数阈值判定` : undefined}
      width={560}
      footer={
        <>
          <Button onClick={close}>关闭</Button>
          <Button
            variant="primary"
            disabled={!topic || running}
            loading={running}
            onClick={() => void run()}
          >
            {score ? '重新评分' : '开始评分'}
          </Button>
        </>
      }
    >
      {topic ? (
        <div className="stack" style={{ gap: 12 }}>
          {score ? (
            <>
              <div className="row" style={{ gap: 8, alignItems: 'center' }}>
                <Chip tone={score.verdict === 'do' ? 'accent' : score.verdict === 'pivot' ? 'warn' : 'danger'}>
                  {verdict?.label}
                </Chip>
                <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>{verdict?.hint}</span>
                <span style={{ marginLeft: 'auto', fontSize: 13, fontWeight: 600 }} data-testid="score-total">
                  总分 {score.total}/35
                </span>
              </div>
              <div className="stack" style={{ gap: 7 }}>
                {DIM_ROWS.map((d) => (
                  <div className="dim-row" key={d.key}>
                    <span className="dim-label">{d.label}</span>
                    <span className="dim-bar">
                      <i style={{ width: `${(score.dims[d.key] / 5) * 100}%` }} />
                    </span>
                    <span className="dim-score">{score.dims[d.key]}</span>
                  </div>
                ))}
              </div>
              {score.reason ? (
                <p style={{ margin: 0, fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.55 }}>
                  {score.reason}
                </p>
              ) : null}
            </>
          ) : (
            <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-3)' }}>
              还没有评分。流量 / 匹配 / 差异化 / 时效 / 变现 / 成本 / 风险各 1–5 分，
              总分 ≥ 27 建议做，≤ 18 不做，中间改方向。
            </p>
          )}
        </div>
      ) : null}
      {errorText ? (
        <p className="sysfile danger" style={{ whiteSpace: 'pre-line', marginTop: 10 }} role="alert">
          {errorText}
        </p>
      ) : null}
    </Modal>
  )
}

export default ScoreDialog
