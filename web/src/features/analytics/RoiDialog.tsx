/** F-G34 投入台账录入弹层：hours/amount ≥ 0 且至少一项 > 0（后端 422 同口径）。
 *
 * 记录下拉可不选（投入可先于发布记录存在，roi_entries.record_id 无外键）。
 * 422 等错误一律 describeError 渲染在弹层内 role="alert"。
 */

import { useEffect, useState } from 'react'
import { Button, Input, Modal, Select, Textarea } from '@/components'
import { describeError } from '@/lib/gates'
import { attributionApi } from './api'
import type { RecentRecord } from './types'

export type RoiDialogProps = {
  open: boolean
  onClose: () => void
  onSaved: () => void
}

export function RoiDialog({ open, onClose, onSaved }: RoiDialogProps) {
  const [records, setRecords] = useState<RecentRecord[]>([])
  const [recordId, setRecordId] = useState('')
  const [project, setProject] = useState('')
  const [hours, setHours] = useState('')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [running, setRunning] = useState(false)
  const [errorText, setErrorText] = useState('')

  useEffect(() => {
    if (!open) return
    setRecordId('')
    setProject('')
    setHours('')
    setAmount('')
    setNote('')
    setErrorText('')
    let alive = true
    attributionApi
      .recordsRecent()
      .then((r) => {
        if (alive) setRecords(r.items ?? [])
      })
      .catch(() => {
        if (alive) setRecords([]) // api 层已 toast；记录只是可选挂载点
      })
    return () => {
      alive = false
    }
  }, [open])

  const submit = async () => {
    const h = Number(hours) || 0
    const a = Number(amount) || 0
    if (h <= 0 && a <= 0) {
      setErrorText('hours 与 amount 至少一项大于 0——只花时间就填 hours，只花钱就填 amount')
      return
    }
    setRunning(true)
    setErrorText('')
    try {
      await attributionApi.createRoi({
        record_id: recordId,
        project: project.trim(),
        hours: h,
        amount: a,
        note: note.trim(),
      })
      onSaved()
      onClose()
    } catch (e) {
      setErrorText(describeError(e))
    } finally {
      setRunning(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="记一笔投入"
      sub="写这篇花了几个小时 / 花了多少钱——ROI 只算真实台账，不编产出比"
      width={520}
      footer={
        <>
          <Button onClick={onClose}>取消</Button>
          <Button variant="primary" loading={running} onClick={() => void submit()}>
            记一笔
          </Button>
        </>
      }
    >
      <div className="stack" style={{ gap: 10 }}>
        <Select
          label="挂到发布记录（可选）"
          placeholder="不挂记录"
          options={records.map((r) => ({
            value: r.id,
            label: `${r.platform} · ${r.title || r.draft_title || '（无标题）'} · ${r.created_at.slice(0, 10)}`,
          }))}
          value={recordId}
          onChange={(e) => setRecordId(e.target.value)}
        />
        <Input
          label="项目名（可选）"
          value={project}
          placeholder="如：双11 知识卡系列"
          onChange={(e) => setProject(e.target.value)}
        />
        <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 140 }}>
            <Input
              label="投入小时数"
              type="number"
              min={0}
              step="0.5"
              value={hours}
              placeholder="0"
              onChange={(e) => setHours(e.target.value)}
            />
          </div>
          <div style={{ flex: 1, minWidth: 140 }}>
            <Input
              label="投入金额（元）"
              type="number"
              min={0}
              step="0.01"
              value={amount}
              placeholder="0"
              onChange={(e) => setAmount(e.target.value)}
            />
          </div>
        </div>
        <Textarea label="备注（可选）" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      {errorText ? (
        <p className="sysfile danger" style={{ whiteSpace: 'pre-line', marginBottom: 4 }} role="alert">
          {errorText}
        </p>
      ) : null}
    </Modal>
  )
}

export default RoiDialog
