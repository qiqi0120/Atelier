import { useRef, useState } from 'react'
import type { ClipboardEvent, ChangeEvent, KeyboardEvent } from 'react'
import { FolderOpen, Mic, Paperclip, Send, Trash2 } from 'lucide-react'
import { Button, Chip } from '@/components'
import type { Attachment } from '@/lib/types'
import { HeartbeatHint } from './HeartbeatHint'
import { StreamStopButton } from './StreamStopButton'

export type ComposerProps = {
  value: string
  onChange: (text: string) => void
  onSend: () => void
  onStop: () => void
  streaming: boolean
  lastEventAt: number
  reconnecting?: boolean
  attachments: Attachment[]
  onPickFiles: (files: File[]) => void
  onRemoveAttachment: (id: string) => void
  disabledReason?: string
}

const MAX_FILE_BYTES = 200 * 1024 * 1024

/** 文件类型白名单（与后端一致，前端先拦一道给出即时反馈） */
function acceptAttr(): string {
  return 'image/*,video/*,audio/*,.pdf,.docx,.md,.txt,.csv,.xlsx'
}

/**
 * 输入框（UI-SPEC 规则 5 / 8）：
 * - Enter 发送、Shift+Enter 换行
 * - 素材三通道：按钮选择 / 拖拽（`.cbox.drag` 高亮）/ 粘贴剪贴板里的图片
 * - 附件 chip 挂在输入框**上方**，消息区只显示用户实际输入的文字
 */
export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  streaming,
  lastEventAt,
  reconnecting = false,
  attachments,
  onPickFiles,
  onRemoveAttachment,
  disabledReason,
}: ComposerProps) {
  const [dragging, setDragging] = useState(false)
  const [stopping, setStopping] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const canSend = Boolean(value.trim() || attachments.length) && !streaming

  const submit = () => {
    if (streaming || disabledReason) return
    if (!value.trim() && !attachments.length) return
    onSend()
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Enter') return
    if (e.shiftKey || e.nativeEvent.isComposing) return // Shift+Enter 换行 / 中文输入法回车不发送
    e.preventDefault()
    submit()
  }

  const onPaste = (e: ClipboardEvent<HTMLDivElement>) => {
    const items = Array.from(e.clipboardData?.items ?? [])
    const files = items
      .filter((it) => it.kind === 'file' && it.type.startsWith('image/'))
      .map((it) => it.getAsFile())
      .filter((f): f is File => Boolean(f))
    if (files.length) {
      e.preventDefault()
      onPickFiles(files)
    }
  }

  const guardSize = (files: File[]): File[] => {
    const tooBig = files.find((f) => f.size > MAX_FILE_BYTES)
    if (tooBig) {
      window.alert(`「${tooBig.name}」超过 200MB 上限，先压缩或裁剪后再传`)
      return []
    }
    return files
  }

  return (
    <div className="composer">
      <div className="composer-in">
        <div
          className={`cbox ${dragging ? 'drag' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            const files = Array.from(e.dataTransfer?.files ?? [])
            if (files.length) onPickFiles(guardSize(files))
          }}
          onPaste={onPaste}
        >
          {attachments.length ? (
            <div className="att" style={{ padding: '8px 12px 0' }}>
              {attachments.map((a) => (
                <span className="f" key={a.id} title={a.path}>
                  <i className="th">{(a.name.split('.').pop() ?? 'file').slice(0, 3).toUpperCase()}</i>
                  {a.name}
                  <span
                    className="x"
                    role="button"
                    aria-label={`移除 ${a.name}`}
                    onClick={() => onRemoveAttachment(a.id)}
                  >
                    ✕
                  </span>
                </span>
              ))}
            </div>
          ) : null}

          <textarea
            ref={taRef}
            rows={1}
            value={value}
            placeholder="说清楚你要什么，比如「把这条热点写成公众号长文，2000 字，分 3 个小标题」"
            onChange={(e: ChangeEvent<HTMLTextAreaElement>) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
          />

          <div className="cbar">
            <input
              ref={fileRef}
              type="file"
              multiple
              hidden
              accept={acceptAttr()}
              onChange={(e) => {
                const files = Array.from(e.target.files ?? [])
                if (files.length) onPickFiles(guardSize(files))
                e.target.value = ''
              }}
            />
            <button type="button" className="iconbtn" title="上传素材（可拖拽/粘贴）" onClick={() => fileRef.current?.click()}>
              <Paperclip size={16} />
            </button>
            <button type="button" className="iconbtn" title="引用内容库文件" disabled>
              <FolderOpen size={16} />
            </button>
            <button type="button" className="iconbtn rec" title="语音输入（M3 接入）" disabled>
              <Mic size={16} />
            </button>

            <div style={{ flex: 1, display: 'flex', gap: 8, alignItems: 'center' }}>
              <HeartbeatHint active={streaming} lastEventAt={lastEventAt} />
              {reconnecting ? <span className="typing">断线了，正在重连…</span> : null}
            </div>

            <button type="button" className="iconbtn" title="清空输入" onClick={() => onChange('')}>
              <Trash2 size={16} />
            </button>
            {streaming ? (
              <StreamStopButton
                stopping={stopping}
                onStop={() => {
                  setStopping(true)
                  onStop()
                  window.setTimeout(() => setStopping(false), 400)
                }}
              />
            ) : (
              <Button
                variant="primary"
                icon={Send}
                disabled={!canSend}
                disabledReason={disabledReason ?? (canSend ? undefined : '先说点什么，或拖一个素材进来')}
                onClick={submit}
              >
                发送
              </Button>
            )}
          </div>
        </div>

        <div className="row" style={{ marginTop: 7, gap: 8 }}>
          <span className="help">Enter 发送 · Shift+Enter 换行 · 素材可直接拖入或粘贴</span>
          <Chip tone="outline" mono style={{ marginLeft: 'auto' }}>
            {streaming ? '生成中 · 可随时停止' : '对话通道已连通'}
          </Chip>
        </div>
      </div>
    </div>
  )
}

export default Composer
