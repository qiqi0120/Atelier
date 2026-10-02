/** SPEC-09 §6 · 事件编辑弹层：新建（event=null）与编辑/删除（event 非空）三合一。 */

import { useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { Button, Field, Input, Modal, Select, Textarea } from '@/components'
import { calendarApi } from './api'
import { KIND_LABEL, KIND_VALUES, type CalEvent, type CalKind } from './types'

const KIND_OPTIONS = KIND_VALUES.map((k) => ({ value: k, label: KIND_LABEL[k] }))

export type EventDialogProps = {
  open: boolean
  event: CalEvent | null
  onClose: () => void
  onSaved: () => void
  onRequestDelete: (event: CalEvent) => void
}

export function EventDialog({ open, event, onClose, onSaved, onRequestDelete }: EventDialogProps) {
  const editing = event !== null
  const [title, setTitle] = useState('')
  const [date, setDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [kind, setKind] = useState<CalKind>('festival')
  const [note, setNote] = useState('')
  const [remindDays, setRemindDays] = useState('3')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setTitle(event?.title ?? '')
    setDate(event?.date ?? '')
    setEndDate(event?.end_date ?? '')
    setKind(event?.kind ?? 'festival')
    setNote(event?.note ?? '')
    setRemindDays(String(event?.remind_days ?? 3))
  }, [open, event])

  const close = () => {
    onClose()
  }

  const submit = async () => {
    if (!title.trim() || !date || saving) return
    setSaving(true)
    try {
      const body = {
        title: title.trim(),
        date,
        kind,
        end_date: editing ? endDate : endDate || undefined,
        note: note.trim() || undefined,
        remind_days: Number(remindDays) || 0,
      }
      if (editing && event) {
        await calendarApi.update(event.id, body)
      } else {
        await calendarApi.create(body)
      }
      onSaved()
      onClose()
    } catch {
      // api 层已 toast（非 2xx 自动提示），页面只兜住 loading
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title={editing ? '编辑节点' : '新建事件'}
      sub={editing && event?.source === 'builtin' ? '内置节点：可以改也可以删，重新导入会带回。' : undefined}
      width={520}
      footer={
        <>
          {editing && event ? (
            <Button
              variant="danger"
              icon={Trash2}
              onClick={() => onRequestDelete(event)}
            >
              删除
            </Button>
          ) : null}
          <span style={{ flex: 1 }} />
          <Button onClick={close}>取消</Button>
          <Button
            variant="primary"
            disabled={!title.trim() || !date}
            loading={saving}
            disabledReason={!title.trim() ? '给节点起个名字' : !date ? '选个日期' : undefined}
            onClick={() => void submit()}
          >
            {editing ? '保存' : '创建'}
          </Button>
        </>
      }
    >
      <div className="stack" style={{ gap: 12 }}>
        <Field label="名称" required help="如：双11、新品发布会、行业峰会（最长 80 字）">
          {(id) => (
            <Input
              id={id}
              value={title}
              maxLength={80}
              onChange={(e) => setTitle(e.target.value)}
            />
          )}
        </Field>
        <div className="row" style={{ gap: 12 }}>
          <div style={{ flex: 1 }}>
            <Field label="开始日期" required>
              {(id) => <Input id={id} type="date" value={date} onChange={(e) => setDate(e.target.value)} />}
            </Field>
          </div>
          <div style={{ flex: 1 }}>
            <Field label="结束日期" help="多日活动才需要（可选）">
              {(id) => <Input id={id} type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />}
            </Field>
          </div>
        </div>
        <div className="row" style={{ gap: 12 }}>
          <div style={{ width: 200 }}>
            <Field label="类型">
              {(id) => (
                <Select id={id} options={KIND_OPTIONS} value={kind} onChange={(e) => setKind(e.target.value as CalKind)} />
              )}
            </Field>
          </div>
          <div style={{ width: 160 }}>
            <Field label="提前提醒" help="0–30 天">
              {(id) => (
                <Input
                  id={id}
                  type="number"
                  min={0}
                  max={30}
                  value={remindDays}
                  onChange={(e) => setRemindDays(e.target.value)}
                />
              )}
            </Field>
          </div>
        </div>
        <Field label="备注" help="给这条节点的上下文，建议生成时会用到（可选）">
          {(id) => (
            <Textarea id={id} rows={2} maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} />
          )}
        </Field>
      </div>
    </Modal>
  )
}

export default EventDialog
