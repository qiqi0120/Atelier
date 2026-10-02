/** SPEC-12 §4 · 日报历史抽屉：列表 + markdown 详情（日报只追加，不提供编辑/删除）。 */

import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button, Drawer, EmptyState } from '@/components'
import { describeError } from '@/lib/gates'
import { discoveryApi } from './api'
import type { HotDigest } from './types'

export type DigestHistoryDrawerProps = {
  open: boolean
  onClose: () => void
}

export function DigestHistoryDrawer({ open, onClose }: DigestHistoryDrawerProps) {
  const [items, setItems] = useState<HotDigest[]>([])
  const [current, setCurrent] = useState<HotDigest | null>(null)
  const [errorText, setErrorText] = useState('')

  useEffect(() => {
    if (!open) return
    setErrorText('')
    discoveryApi
      .digests()
      .then((r) => setItems(r.items))
      .catch((e) => setErrorText(describeError(e)))
  }, [open])

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="日报历史"
      meta={current ? current.title : `${items.length} 份日报（只追加，不可改）`}
      footer={
        current ? (
          <Button onClick={() => setCurrent(null)}>返回列表</Button>
        ) : (
          <Button onClick={onClose}>关闭</Button>
        )
      }
    >
      {errorText ? <p className="sysfile danger">{errorText}</p> : null}
      {current ? (
        <div className="md" style={{ fontSize: 13 }}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{current.markdown}</ReactMarkdown>
        </div>
      ) : items.length === 0 && !errorText ? (
        <EmptyState
          title="还没有生成过日报"
          description="素材池有「待处理」热点后，点页首的「生成日报」。"
        />
      ) : (
        items.map((d) => (
          <button
            key={d.id}
            type="button"
            className="task"
            style={{ width: '100%', textAlign: 'left', cursor: 'pointer' }}
            onClick={() => setCurrent(d)}
            data-testid="digest-row"
          >
            <div className="tx">
              <b>{d.title}</b>
              <span>
                覆盖 {d.window_start || '?'} ~ {d.window_end || '?'} · {d.entry_ids.length} 条素材
              </span>
            </div>
          </button>
        ))
      )}
    </Drawer>
  )
}

export default DigestHistoryDrawer
