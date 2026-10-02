/** SPEC-08 §6 · F-E10 内容矩阵弹层：支柱 × 格式 → 选题池（整批入库到待做列）。 */

import { useState } from 'react'
import { Button, Field, Modal, Select, Textarea, toast } from '@/components'
import { useAtelier } from '@/lib/store'
import { topicsApi } from './api'
import { describeError } from '@/lib/gates'
import type { MatrixResult } from './types'

const PER_COMBO_OPTIONS = [
  { value: '1', label: '每格 1 条' },
  { value: '2', label: '每格 2 条' },
  { value: '3', label: '每格 3 条' },
]

export type MatrixDialogProps = {
  open: boolean
  onClose: () => void
  onSaved: () => void
}

const PLACEHOLDER_PILLARS = '通勤穿搭\n平价好物\n职场成长'
const PLACEHOLDER_FORMATS = '图文\n短视频\n合集'

export function MatrixDialog({ open, onClose, onSaved }: MatrixDialogProps) {
  const { profile } = useAtelier()
  const profileId = profile && !profile.generalMode ? profile.id : undefined

  const [pillarsDraft, setPillarsDraft] = useState('')
  const [formatsDraft, setFormatsDraft] = useState('')
  const [perCombo, setPerCombo] = useState('2')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<MatrixResult | null>(null)
  const [errorText, setErrorText] = useState('')

  const pillars = pillarsDraft.split('\n').map((s) => s.trim()).filter(Boolean)
  const formats = formatsDraft.split('\n').map((s) => s.trim()).filter(Boolean)
  const combos = pillars.length * formats.length * Number(perCombo || 0)

  const close = () => {
    setResult(null)
    setErrorText('')
    setPillarsDraft('')
    setFormatsDraft('')
    setPerCombo('2')
    onClose()
  }

  const run = async () => {
    setRunning(true)
    setErrorText('')
    try {
      setResult(
        await topicsApi.matrix({
          pillars,
          formats,
          per_combo: Number(perCombo),
          profile_id: profileId,
        }),
      )
    } catch (e) {
      setErrorText(describeError(e))
    } finally {
      setRunning(false)
    }
  }

  const finish = () => {
    if (result && result.count > 0) toast.ok(`已生成 ${result.count} 条选题（待做列）`)
    onSaved()
    close()
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="内容矩阵"
      sub="内容支柱 × 格式 交叉出选题，一键填满选题池"
      width={640}
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
              disabled={pillars.length === 0 || formats.length === 0 || combos > 60 || running}
              loading={running}
              disabledReason={combos > 60 ? `组合数 ${combos} 超过单次上限 60，请缩小范围` : undefined}
              onClick={() => void run()}
            >
              生成选题池
            </Button>
          </>
        )
      }
    >
      {result ? (
        <div className="stack" style={{ gap: 10 }}>
          <p style={{ margin: 0, color: 'var(--ink-2)', fontSize: 13 }}>
            已入库 <b style={{ color: 'var(--accent-ink)' }}>{result.count}</b> 条选题，都在「待做」列。
          </p>
          <div className="stack" style={{ gap: 6 }}>
            {result.items.slice(0, 8).map((t) => (
              <div key={t.id} className="row" style={{ gap: 8, fontSize: 13 }}>
                <span style={{ color: 'var(--muted)', fontSize: 11.5, width: 110, flex: 'none' }}>
                  {t.source_ref}
                </span>
                <span>{t.title}</span>
              </div>
            ))}
            {result.count > 8 ? (
              <p style={{ margin: 0, fontSize: 12, color: 'var(--ink-3)' }}>
                …其余 {result.count - 8} 条在看板里
              </p>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="stack" style={{ gap: 12 }}>
          <Field label="内容支柱" required help="账号的选题方向，每行一个，最多 6 个">
            {(id) => (
              <Textarea
                id={id}
                rows={4}
                placeholder={PLACEHOLDER_PILLARS}
                value={pillarsDraft}
                onChange={(e) => setPillarsDraft(e.target.value)}
              />
            )}
          </Field>
          <Field label="内容格式" required help="每行一个，最多 6 个">
            {(id) => (
              <Textarea
                id={id}
                rows={3}
                placeholder={PLACEHOLDER_FORMATS}
                value={formatsDraft}
                onChange={(e) => setFormatsDraft(e.target.value)}
              />
            )}
          </Field>
          <div className="row" style={{ gap: 12, alignItems: 'center' }}>
            <div style={{ width: 160 }}>
              <Field label="每格条数">
                {(id) => (
                  <Select
                    id={id}
                    options={PER_COMBO_OPTIONS}
                    value={perCombo}
                    onChange={(e) => setPerCombo(e.target.value)}
                  />
                )}
              </Field>
            </div>
            <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>
              合计 {combos || 0} 条（单次上限 60）
            </span>
          </div>
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

export default MatrixDialog
