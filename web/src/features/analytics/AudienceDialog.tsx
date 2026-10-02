/** SPEC-11 §4 · F-E14 受众画像卡弹层：人群一句 + 痛点/场景/偏好/避坑。 */

import { useState } from 'react'
import { Button, Card, Chip, Modal } from '@/components'
import { useAtelier } from '@/lib/store'
import { describeError } from '@/lib/gates'
import { analyticsApi } from './api'
import type { InsightCard, AudienceResult } from './types'

export type AudienceDialogProps = {
  open: boolean
  onClose: () => void
}

const SECTIONS: { key: keyof Omit<InsightCard, 'persona'>; label: string }[] = [
  { key: 'pains', label: '痛点' },
  { key: 'scenarios', label: '典型场景' },
  { key: 'preferences', label: '内容偏好' },
  { key: 'notes', label: '避坑提醒' },
]

export function AudienceDialog({ open, onClose }: AudienceDialogProps) {
  const profile = useAtelier((s) => s.profile)
  const profileId = profile && !profile.generalMode ? profile.id : undefined

  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<AudienceResult | null>(null)
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
      setResult(await analyticsApi.audience(profileId))
    } catch (e) {
      setErrorText(describeError(e))
    } finally {
      setRunning(false)
    }
  }

  const card = result?.card

  return (
    <Modal
      open={open}
      onClose={close}
      title="受众画像卡"
      sub={profileId ? `基于画像「${profile?.name}」推断` : '通用模式（未绑定画像），卡片会标注「通用版」'}
      width={560}
      footer={
        result ? (
          <Button variant="primary" onClick={close}>
            完成
          </Button>
        ) : (
          <>
            <Button onClick={close}>取消</Button>
            <Button variant="primary" loading={running} onClick={() => void run()}>
              生成画像卡
            </Button>
          </>
        )
      }
    >
      {card ? (
        <div className="stack" style={{ gap: 10 }}>
          <Card title="目标人群" tight>
            <p style={{ margin: 0, fontSize: 13.5 }}>{card.persona}</p>
          </Card>
          {SECTIONS.map((s) => (
            <div key={s.key}>
              <Chip tone="outline">{s.label}</Chip>
              <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 13 }}>
                {card[s.key].map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : (
        <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-2)' }}>
          提炼一张受众画像卡：目标人群一句话 + 痛点、典型场景、内容偏好、避坑提醒。
          是基于画像的合理推断，不是调研数据。
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

export default AudienceDialog
