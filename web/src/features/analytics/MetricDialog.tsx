/** F-G31 内容表现录入弹层：发布记录下拉来自 /attribution/records-recent，
 * 选中自动带平台（平台不可手改——表现必须挂在同一条平台记录上）。
 *
 * 三态：records=null 加载 / running / errorText（describeError 渲 role="alert"）。
 */

import { useEffect, useState } from 'react'
import { Button, Input, Modal, Select, Skeleton, Textarea } from '@/components'
import type { SelectOption } from '@/components'
import { describeError } from '@/lib/gates'
import { attributionApi } from './api'
import { todayStr } from './SnapshotDialog'
import type { RecentRecord } from './types'

export type MetricDialogProps = {
  open: boolean
  onClose: () => void
  onSaved: () => void
}

function recordLabel(r: RecentRecord): string {
  const title = r.title || r.draft_title || '（无标题）'
  return `${r.platform} · ${title} · ${r.created_at.slice(0, 10)}`
}

export function MetricDialog({ open, onClose, onSaved }: MetricDialogProps) {
  const [records, setRecords] = useState<RecentRecord[] | null>(null)
  const [recordId, setRecordId] = useState('')
  const [views, setViews] = useState('0')
  const [likes, setLikes] = useState('0')
  const [comments, setComments] = useState('0')
  const [shares, setShares] = useState('0')
  const [collectedAt, setCollectedAt] = useState(todayStr())
  const [note, setNote] = useState('')
  const [running, setRunning] = useState(false)
  const [errorText, setErrorText] = useState('')

  useEffect(() => {
    if (!open) return
    setRecordId('')
    setViews('0')
    setLikes('0')
    setComments('0')
    setShares('0')
    setCollectedAt(todayStr())
    setNote('')
    setErrorText('')
    let alive = true
    setRecords(null)
    attributionApi
      .recordsRecent()
      .then((r) => {
        if (alive) setRecords(r.items ?? [])
      })
      .catch((e) => {
        if (!alive) return
        setRecords([])
        setErrorText(describeError(e))
      })
    return () => {
      alive = false
    }
  }, [open])

  const selected = records?.find((r) => r.id === recordId) ?? null
  const options: SelectOption[] = (records ?? []).map((r) => ({ value: r.id, label: recordLabel(r) }))

  const submit = async () => {
    if (!selected) {
      setErrorText('先选一条发布记录——表现数据必须挂在具体记录上')
      return
    }
    setRunning(true)
    setErrorText('')
    try {
      await attributionApi.createMetric({
        record_id: selected.id,
        platform: selected.platform,
        views: Number(views) || 0,
        likes: Number(likes) || 0,
        comments: Number(comments) || 0,
        shares: Number(shares) || 0,
        collected_at: collectedAt,
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
      title="录入内容表现"
      sub="从创作者中心抄这条内容的播放/点赞/评论/转发——看板与复盘只吃真实录入"
      width={520}
      footer={
        <>
          <Button onClick={onClose}>取消</Button>
          <Button
            variant="primary"
            loading={running}
            disabled={records !== null && records.length === 0}
            disabledReason={records !== null && records.length === 0 ? '还没有发布记录，先去发布一条（dry-run 也算）' : undefined}
            onClick={() => void submit()}
          >
            录入表现
          </Button>
        </>
      }
    >
      {records === null ? (
        <div className="stack" style={{ gap: 8, padding: '6px 0' }}>
          <Skeleton width="70%" height={34} />
          <Skeleton width="100%" height={34} />
        </div>
      ) : (
        <div className="stack" style={{ gap: 10 }}>
          <Select
            label="发布记录"
            required
            placeholder="选一条发布记录"
            options={options}
            value={recordId}
            onChange={(e) => setRecordId(e.target.value)}
            help={`选项是「平台 · 标题 · 时间」，共 ${records.length} 条（最近 20 条内）`}
          />
          <Input
            label="平台（随所选记录）"
            value={selected?.platform ?? ''}
            readOnly
            disabled
            help="平台不能手改：表现数据必须与发布记录同平台"
          />
          <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 110 }}>
              <Input label="播放" type="number" min={0} value={views} onChange={(e) => setViews(e.target.value)} />
            </div>
            <div style={{ flex: 1, minWidth: 110 }}>
              <Input label="点赞" type="number" min={0} value={likes} onChange={(e) => setLikes(e.target.value)} />
            </div>
            <div style={{ flex: 1, minWidth: 110 }}>
              <Input label="评论" type="number" min={0} value={comments} onChange={(e) => setComments(e.target.value)} />
            </div>
            <div style={{ flex: 1, minWidth: 110 }}>
              <Input label="转发" type="number" min={0} value={shares} onChange={(e) => setShares(e.target.value)} />
            </div>
          </div>
          <Input
            label="抄录日期"
            required
            type="date"
            value={collectedAt}
            onChange={(e) => setCollectedAt(e.target.value)}
          />
          <Textarea
            label="备注（可选）"
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
      )}
      {errorText ? (
        <p className="sysfile danger" style={{ whiteSpace: 'pre-line', marginBottom: 4 }} role="alert">
          {errorText}
        </p>
      ) : null}
    </Modal>
  )
}

export default MetricDialog
