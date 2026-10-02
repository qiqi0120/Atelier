/** SPEC-12 §4 · F-D8 热点日报弹层：AI 三态（running/result/error）+ insufficient 诚实空态。 */

import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button, EmptyState, Modal } from '@/components'
import { describeError } from '@/lib/gates'
import { discoveryApi } from './api'
import type { DigestResponse } from './types'

export type DigestDialogProps = {
  open: boolean
  onClose: () => void
  profileId?: string
  onDone?: () => void
}

export function DigestDialog({ open, onClose, profileId, onDone }: DigestDialogProps) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<DigestResponse | null>(null)
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
      const r = await discoveryApi.digest(profileId)
      setResult(r)
      if (!r.insufficient) onDone?.()
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
      title="热点日报"
      sub={profileId ? '基于当前画像给建议' : '通用模式：日报会如实标注未绑定画像'}
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
              生成日报
            </Button>
          </>
        )
      }
    >
      {result ? (
        result.insufficient ? (
          <EmptyState
            title="素材池没有待处理的热点"
            description={result.message}
            actionLabel="先去导入或从订阅转入"
            onAction={close}
          />
        ) : (
          <div style={{ fontSize: 13, maxHeight: '58vh', overflow: 'auto' }}>
            <p className="sysfile" style={{ marginTop: 0 }}>
              已把 {result.entry_count} 条素材标为「已进日报」，日报存入历史可回看。
            </p>
            <div className="md">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.markdown}</ReactMarkdown>
            </div>
          </div>
        )
      ) : (
        <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-2)' }}>
          把素材池里「待处理」的热点聚合成三段式日报：热点盘点 / 机会点 / 建议动作。
          只解读已导入的素材，不编造热点；素材池为空会直接说明，不生成假日报。
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

export default DigestDialog
