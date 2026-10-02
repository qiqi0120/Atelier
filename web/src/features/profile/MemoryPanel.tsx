import { useState } from 'react'
import { Plus, X } from 'lucide-react'
import { Button, Chip, Textarea, toast } from '@/components'
import type { Memory } from '@/lib/types'

export type MemoryPanelProps = {
  memories: Memory[]
  onAdd: (text: string) => Promise<void>
  onDelete: (memoryId: string) => Promise<void>
}

/** 相对时间：记忆列表要一眼看出「多久前的结论」（原型 mem-item 第二行） */
function ago(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const days = Math.floor((Date.now() - then) / 86_400_000)
  if (days <= 0) return '今天'
  if (days === 1) return '昨天'
  if (days < 30) return `${days} 天前`
  const months = Math.floor(days / 30)
  return months < 12 ? `${months} 个月前` : `${Math.floor(months / 12)} 年前`
}

/**
 * 长期记忆面板（PRD F-A6 / spec 验收 7）：列表 + 手动记一条。
 * 加完立刻 toast「已记住，下一轮对话生效」——它进的是 system_prompt 前缀，不是某个会话。
 */
export function MemoryPanel({ memories, onAdd, onDelete }: MemoryPanelProps) {
  const [draft, setDraft] = useState('')
  const [adding, setAdding] = useState(false)

  const submit = async () => {
    const text = draft.trim()
    if (!text || adding) return
    setAdding(true)
    try {
      await onAdd(text)
      setDraft('')
      toast.ok('已记住，下一轮对话生效')
    } finally {
      setAdding(false)
    }
  }

  return (
    <div className="card">
      <div className="card-h">
        <h3>长期记忆</h3>
        <div className="sp">
          <Chip tone="outline">{memories.length} 条</Chip>
        </div>
      </div>
      <div className="card-b">
        {memories.length === 0 ? (
          <div className="help" style={{ padding: '4px 0 8px' }}>
            还没有长期记忆。发完一轮后去「数据复盘」把结论沉淀进来，或在这里手动记一条——
            记忆会直接进下一轮的系统提示，不是某个会话的临时状态。
          </div>
        ) : (
          <div>
            {memories.map((m, i) => (
              <div className="mem-item" key={m.id}>
                <div className="q">{i + 1}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <b>{m.text}</b>
                  <span>
                    {m.source} · {ago(m.created_at)} · 下一轮对话自动注入
                  </span>
                </div>
                <button
                  type="button"
                  className="iconbtn"
                  aria-label={`删除记忆：${m.text}`}
                  onClick={() => void onDelete(m.id)}
                >
                  <X size={13} />
                </button>
              </div>
            ))}
          </div>
        )}

        <div style={{ marginTop: 10 }}>
          <Textarea
            label="手动记一条"
            placeholder="例：标题不要用「震惊 / 必看」这类极限词"
            rows={2}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="row" style={{ marginTop: 8, justifyContent: 'flex-end' }}>
            <span className="help" style={{ flex: 1 }}>
              写成一句「下次别再犯」的话，比整段复盘有用
            </span>
            <Button size="sm" variant="primary" icon={Plus} loading={adding} disabled={!draft.trim()} onClick={() => void submit()}>
              记下来
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default MemoryPanel
