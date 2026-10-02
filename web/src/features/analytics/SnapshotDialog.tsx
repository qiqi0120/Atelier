/** F-G29 账号快照录入弹层：把创作中心的数字抄进来（平台不提供公开数据接口）。
 *
 * 三态：表单 / running / errorText（describeError 渲 role="alert"）。
 * 201 后 toast.ok 并触发父级刷新卡内「最近一条」小字。
 */

import { useEffect, useState } from 'react'
import { Button, Field, Input, Modal, Select, Textarea } from '@/components'
import type { SelectOption } from '@/components'
import { describeError } from '@/lib/gates'
import { attributionApi } from './api'
import { ENTRY_PLATFORMS } from './types'

const PLATFORM_OPTIONS: SelectOption[] = ENTRY_PLATFORMS.map((p) => ({ value: p, label: p }))

/** 本地日期的 YYYY-MM-DD（toISOString 是 UTC，会差一天） */
export function todayStr(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export type SnapshotDialogProps = {
  open: boolean
  onClose: () => void
  /** 录入成功（201）后回调：父级刷新小字 */
  onSaved: () => void
}

export function SnapshotDialog({ open, onClose, onSaved }: SnapshotDialogProps) {
  const [platform, setPlatform] = useState('')
  const [capturedAt, setCapturedAt] = useState(todayStr())
  const [followers, setFollowers] = useState('0')
  const [likesTotal, setLikesTotal] = useState('0')
  const [worksTotal, setWorksTotal] = useState('0')
  const [note, setNote] = useState('')
  const [running, setRunning] = useState(false)
  const [errorText, setErrorText] = useState('')

  useEffect(() => {
    if (open) {
      setPlatform('')
      setCapturedAt(todayStr())
      setFollowers('0')
      setLikesTotal('0')
      setWorksTotal('0')
      setNote('')
      setErrorText('')
    }
  }, [open])

  const submit = async () => {
    if (!platform) {
      setErrorText('先选平台——快照必须挂在具体平台上')
      return
    }
    setRunning(true)
    setErrorText('')
    try {
      await attributionApi.createSnapshot({
        platform,
        captured_at: capturedAt,
        followers: Number(followers) || 0,
        likes_total: Number(likesTotal) || 0,
        works_total: Number(worksTotal) || 0,
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
      title="录入账号快照"
      sub="打开创作者中心，把粉丝数、累计获赞、作品数抄进来——只录真实数字"
      width={520}
      footer={
        <>
          <Button onClick={onClose}>取消</Button>
          <Button variant="primary" loading={running} onClick={() => void submit()}>
            录入快照
          </Button>
        </>
      }
    >
      <div className="stack" style={{ gap: 10 }}>
        <Select
          label="平台"
          required
          placeholder="选平台"
          options={PLATFORM_OPTIONS}
          value={platform}
          onChange={(e) => setPlatform(e.target.value)}
        />
        <Input
          label="快照日期"
          required
          type="date"
          value={capturedAt}
          onChange={(e) => setCapturedAt(e.target.value)}
          help="格式 YYYY-MM-DD，默认今天"
        />
        <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 120 }}>
            <Input
              label="粉丝数"
              type="number"
              min={0}
              value={followers}
              onChange={(e) => setFollowers(e.target.value)}
            />
          </div>
          <div style={{ flex: 1, minWidth: 120 }}>
            <Input
              label="累计获赞"
              type="number"
              min={0}
              value={likesTotal}
              onChange={(e) => setLikesTotal(e.target.value)}
            />
          </div>
          <div style={{ flex: 1, minWidth: 120 }}>
            <Input
              label="作品数"
              type="number"
              min={0}
              value={worksTotal}
              onChange={(e) => setWorksTotal(e.target.value)}
            />
          </div>
        </div>
        <Field label="备注（可选）">
          {(id) => (
            <Textarea
              id={id}
              rows={2}
              value={note}
              placeholder="如：发完那条合集后截的数"
              onChange={(e) => setNote(e.target.value)}
            />
          )}
        </Field>
      </div>
      {errorText ? (
        <p className="sysfile danger" style={{ whiteSpace: 'pre-line', marginBottom: 4 }} role="alert">
          {errorText}
        </p>
      ) : null}
    </Modal>
  )
}

export default SnapshotDialog
