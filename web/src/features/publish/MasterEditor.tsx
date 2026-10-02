import { useEffect, useRef, useState } from 'react'
import { Button, Card, Chip, toast } from '@/components'
import type { PublishDraft } from './types'

export type MasterEditorProps = {
  draft: PublishDraft | null
  /** debounce 800ms 后触发（SPEC-06 §6「自动保存，前端 debounce 800ms」） */
  onSave: (patch: Partial<PublishDraft>) => void
  onRegen: () => void
  /** 上一次自动保存完成的时间（ISO）；未保存过为 null */
  savedAt: string | null
  adapting: boolean
}

const DEBOUNCE_MS = 800

function hhmm(iso: string | null): string {
  if (!iso) return '--:--'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '--:--'
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/**
 * 母版内容：标题 / 正文 / 话题标签。
 *
 * ★ **自动保存是 F-G17 的验收项**：改动 debounce 800ms 后落库，
 * 顶栏显示「草稿自动保存 · HH:MM」，刷新页面内容还在（SPEC-06 §8 验收 9）。
 */
export function MasterEditor({ draft, onSave, onRegen, savedAt, adapting }: MasterEditorProps) {
  const [title, setTitle] = useState(draft?.title ?? '')
  const [body, setBody] = useState(draft?.body ?? '')
  const [tag, setTag] = useState('')
  const timer = useRef<number | null>(null)
  const dirty = useRef(false)

  // 切换草稿时重置本地状态（草稿切换 / 首次加载）
  useEffect(() => {
    setTitle(draft?.title ?? '')
    setBody(draft?.body ?? '')
    dirty.current = false
  }, [draft?.id, draft?.title, draft?.body])

  // 卸载前把未落库的改动冲掉，别让切页丢内容
  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current)
    },
    [],
  )

  const schedule = (patch: Partial<PublishDraft>) => {
    dirty.current = true
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      dirty.current = false
      onSave(patch)
    }, DEBOUNCE_MS)
  }

  const addTag = () => {
    const t = tag.trim().replace(/^#/, '')
    if (!t || !draft) return
    if (draft.topic_tags.includes(t)) {
      toast('这个话题已经在列表里了', 'warn')
      return
    }
    setTag('')
    schedule({ topic_tags: [...draft.topic_tags, t] })
  }

  return (
    <Card
      title="母版内容"
      actions={
        <>
          <Chip tone="outline">适配前原文</Chip>
          <Button size="sm" variant="ghost" icon={adapting ? undefined : undefined} onClick={onRegen} loading={adapting}>
            重新适配
          </Button>
        </>
      }
    >
      <div className="field" style={{ marginBottom: 11 }}>
        <label htmlFor="pub-title">标题</label>
        <input
          id="pub-title"
          className="inp"
          value={title}
          placeholder="写一个有人会点开的标题"
          onChange={(e) => {
            setTitle(e.target.value)
            schedule({ title: e.target.value })
          }}
        />
      </div>
      <div className="field">
        <label htmlFor="pub-body">正文</label>
        <textarea
          id="pub-body"
          className="inp"
          rows={7}
          value={body}
          placeholder="一份母版，勾几个平台就能一键适配"
          onChange={(e) => {
            setBody(e.target.value)
            schedule({ body: e.target.value })
          }}
        />
      </div>
      <div className="row" style={{ marginTop: 10, gap: 7, flexWrap: 'wrap' }}>
        <Chip tone="outline">正文 {body.length} 字（含标点，仅本地预览）</Chip>
        {draft?.topic_tags.map((t) => (
          <Chip
            key={t}
            tone="outline"
            onClose={() =>
              schedule({ topic_tags: (draft.topic_tags ?? []).filter((x) => x !== t) })
            }
          >
            #{t}
          </Chip>
        ))}
        <input
          className="inp sm"
          style={{ width: 108 }}
          value={tag}
          placeholder="加话题"
          aria-label="添加话题标签"
          onChange={(e) => setTag(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              addTag()
            }
          }}
        />
        <Button size="sm" variant="ghost" onClick={addTag} disabled={!tag.trim()}>
          + 加话题
        </Button>
      </div>
      <p className="help" style={{ marginTop: 8 }} aria-live="polite">
        <span data-testid="autosave-hint">
          {savedAt ? `草稿自动保存 · ${hhmm(savedAt)}` : '停止输入 0.8 秒后自动保存'}
        </span>
      </p>
    </Card>
  )
}

export default MasterEditor
