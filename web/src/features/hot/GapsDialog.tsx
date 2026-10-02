/** SPEC-12 §4 · F-D11 内容缺口弹层：诚实模式（无订阅信号不调模型）+ 证据来自代码统计。 */

import { useState } from 'react'
import { Button, Card, Chip, EmptyState, Modal } from '@/components'
import { describeError } from '@/lib/gates'
import { discoveryApi } from './api'
import type { GapsResponse } from './types'

export type GapsDialogProps = {
  open: boolean
  onClose: () => void
  profileId?: string
}

export function GapsDialog({ open, onClose, profileId }: GapsDialogProps) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<GapsResponse | null>(null)
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
      setResult(await discoveryApi.gaps(profileId))
    } catch (e) {
      setErrorText(describeError(e))
    } finally {
      setRunning(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="内容缺口分析"
      sub="找「高需求低竞争」的方向：订阅信号是需求侧，你的选题/草稿是供给侧"
      width={640}
      footer={
        result ? (
          <Button variant="primary" onClick={close}>
            完成
          </Button>
        ) : (
          <>
            <Button onClick={close}>取消</Button>
            <Button variant="primary" loading={running} onClick={() => void run()}>
              分析缺口
            </Button>
          </>
        )
      }
    >
      {result ? (
        result.insufficient ? (
          <EmptyState
            title="订阅数据还不够"
            description={result.message}
            actionLabel="先去配订阅并抓取"
            onAction={close}
          />
        ) : (
          <div style={{ maxHeight: '58vh', overflow: 'auto' }}>
            <p className="sysfile" style={{ marginTop: 0 }}>
              {result.notice}
            </p>
            <div className="stack" style={{ gap: 10 }}>
              {result.gaps.map((g, i) => (
                <Card key={i} tight>
                  <div className="stack" style={{ gap: 6 }}>
                    <div className="row" style={{ gap: 8 }}>
                      <b>{g.direction}</b>
                      <Chip tone="accent">缺口 {i + 1}</Chip>
                    </div>
                    <p style={{ margin: 0, fontSize: 12.5, color: 'var(--ink-2)' }}>
                      需求：{g.demand}
                    </p>
                    <p style={{ margin: 0, fontSize: 12.5, color: 'var(--ink-2)' }}>
                      空白：{g.evidence}
                    </p>
                    <p style={{ margin: 0, fontSize: 12.5, color: 'var(--accent-ink)' }}>
                      动作：{g.action}
                    </p>
                  </div>
                </Card>
              ))}
            </div>
          </div>
        )
      ) : (
        <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-2)' }}>
          需求侧统计（关键词命中、标题高频词）由代码从订阅内容里算出来，AI 只解读数字给方向；
          没有订阅信号时直接说明，不编结论。分析结果不落库。
        </p>
      )}
      {errorText ? (
        <p className="sysfile danger" style={{ whiteSpace: 'pre-line' }} role="alert">
          {errorText}
        </p>
      ) : null}
    </Modal>
  )
}

export default GapsDialog
