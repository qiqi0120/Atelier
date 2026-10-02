/** SPEC-09 §2 · F-E7 日历建议弹层：近 N 天节点 + 画像 → 选题 → 整批落选题池。
 *
 * 画像跟随当前激活画像（与拆解/矩阵弹层一致）；生成中走 loading，
 * 门禁 BLOCK 由 lib/gates.describeError 渲染逐项改法。
 */

import { useState } from 'react'
import { Button, Field, Input, Modal, toast } from '@/components'
import { useAtelier } from '@/lib/store'
import { describeError } from '@/lib/gates'
import { calendarApi } from './api'
import type { SuggestResult } from './types'

export type SuggestDialogProps = {
  open: boolean
  onClose: () => void
  onSaved: () => void
}

export function SuggestDialog({ open, onClose, onSaved }: SuggestDialogProps) {
  const { profile } = useAtelier()
  const profileId = profile && !profile.generalMode ? profile.id : undefined

  const [days, setDays] = useState('14')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<SuggestResult | null>(null)
  const [errorText, setErrorText] = useState('')

  const close = () => {
    setResult(null)
    setErrorText('')
    setDays('14')
    onClose()
  }

  const run = async () => {
    setRunning(true)
    setErrorText('')
    try {
      setResult(await calendarApi.suggest({ days: Number(days) || 14, profile_id: profileId }))
    } catch (e) {
      setErrorText(describeError(e))
    } finally {
      setRunning(false)
    }
  }

  const finish = () => {
    if (result && result.count > 0) toast.ok(`已生成 ${result.count} 条建议（选题库待做列）`)
    onSaved()
    close()
  }

  const daysNum = Number(days)

  return (
    <Modal
      open={open}
      onClose={close}
      title="生成近 14 天建议"
      sub="结合日历节点与你的画像出选题，直接落进选题池的待做列"
      width={560}
      footer={
        result ? (
          <Button variant="primary" onClick={finish}>
            完成
          </Button>
        ) : (
          <>
            <Button onClick={close}>取消</Button>
            <Button
              variant="primary"
              disabled={!daysNum || daysNum < 1 || daysNum > 31 || running}
              loading={running}
              disabledReason={daysNum > 31 ? '窗口最长 31 天' : undefined}
              onClick={() => void run()}
            >
              生成建议
            </Button>
          </>
        )
      }
    >
      {result ? (
        <div className="stack" style={{ gap: 10 }}>
          <p style={{ margin: 0, color: 'var(--ink-2)', fontSize: 13 }}>
            已入库 <b style={{ color: 'var(--accent-ink)' }}>{result.count}</b> 条选题，都在「待做」列，
            并带上了建议发布日期（日历里也能看到）。
          </p>
          <div className="stack" style={{ gap: 6 }}>
            {result.items.map((t) => (
              <div key={t.id} className="row" style={{ gap: 8, fontSize: 13 }}>
                <span style={{ color: 'var(--muted)', fontSize: 11.5, width: 52, flex: 'none', fontFamily: 'var(--mono)' }}>
                  {t.due_date.slice(5)}
                </span>
                <span>{t.title}</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="stack" style={{ gap: 12 }}>
          <div style={{ width: 160 }}>
            <Field label="建议窗口" help="1–31 天，默认 14">
              {(id) => (
                <Input id={id} type="number" min={1} max={31} value={days} onChange={(e) => setDays(e.target.value)} />
              )}
            </Field>
          </div>
          <p style={{ margin: 0, fontSize: 12.5, color: 'var(--ink-3)' }}>
            画像：{profileId ? profile?.name : '通用模式（未绑定画像）'}。
            窗口内没有节点也能生成通用建议；重复生成会产生重复选题，由你在看板里清理。
          </p>
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

export default SuggestDialog
