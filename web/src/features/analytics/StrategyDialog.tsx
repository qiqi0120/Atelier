/** SPEC-11 §4 · F-E12 内容策略弹层：一键生成 4 段策略（markdown 渲染，不落库）。 */

import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button, Modal } from '@/components'
import { useAtelier } from '@/lib/store'
import { describeError } from '@/lib/gates'
import { analyticsApi } from './api'
import type { StrategyResult } from './types'

export type StrategyDialogProps = {
  open: boolean
  onClose: () => void
}

export function StrategyDialog({ open, onClose }: StrategyDialogProps) {
  const profile = useAtelier((s) => s.profile)
  const profileId = profile && !profile.generalMode ? profile.id : undefined

  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<StrategyResult | null>(null)
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
      setResult(await analyticsApi.strategy(profileId))
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
      title="内容策略"
      sub={profileId ? `基于画像「${profile?.name}」生成` : '通用模式（未绑定画像），生成结果会如实标注'}
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
              生成策略
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
        <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-2)' }}>
          生成四段式策略：内容支柱架构、受众路径、90 天节奏、KPI。不会写入任何文件，
          满意后自行摘取落进选题或画像。
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

export default StrategyDialog
