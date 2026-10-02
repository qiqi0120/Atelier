import { Archive, Pencil, Trash2 } from 'lucide-react'
import { Button, Chip } from '@/components'
import type { Session } from '@/lib/types'
import type { SessionGroup } from './types'

export type SessionListProps = {
  groups: SessionGroup[]
  activeId: string | null
  /** 侧栏底部的画像注入状态（原型左下角那颗点） */
  profileName?: string | null
  profileInjected?: boolean
  onSelect: (id: string) => void
  onNew: () => void
  onRename: (s: Session) => void
  onArchive: (s: Session) => void
  onDelete: (s: Session) => void
  onOpenProfile?: () => void
}

function when(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  const y = new Date(now.getTime() - 86400000)
  if (d.toDateString() === y.toDateString()) return `昨天 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`
}

/** 会话栏：分组（今天/昨天/更早/已归档）+ hover 出重命名/归档（原型 #v-chat 左栏） */
export function SessionList({
  groups,
  activeId,
  profileName,
  profileInjected = false,
  onSelect,
  onNew,
  onRename,
  onArchive,
  onDelete,
  onOpenProfile,
}: SessionListProps) {
  return (
    <aside className="chat-side">
      <div style={{ padding: '12px 12px 8px', borderBottom: '1px solid var(--line-soft)' }}>
        <Button size="sm" style={{ width: '100%', justifyContent: 'center' }} onClick={onNew}>
          ＋ 新会话
        </Button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 8px 12px', minHeight: 0 }}>
        {groups.length === 0 ? (
          <div className="nav-label" style={{ padding: '8px 6px' }}>
            还没有会话
          </div>
        ) : null}
        {groups.map((g) => (
          <div key={g.key}>
            <div className="nav-label" style={{ padding: g.key === 'today' ? '4px 4px 6px' : '10px 4px 6px' }}>
              {g.label}
            </div>
            {g.items.map((s) => (
              <div
                key={s.id}
                className={`sess ${s.id === activeId ? 'on' : ''}`}
                style={g.key === 'archived' ? { opacity: 0.6 } : undefined}
                role="button"
                tabIndex={0}
                onClick={() => onSelect(s.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onSelect(s.id)
                  }
                }}
              >
                <b>{s.title}</b>
                <span>{when(s.updated_at)}</span>
                <div className="act">
                  <button
                    type="button"
                    title="重命名"
                    onClick={(e) => {
                      e.stopPropagation()
                      onRename(s)
                    }}
                  >
                    <Pencil size={12} />
                  </button>
                  <button
                    type="button"
                    title="归档"
                    onClick={(e) => {
                      e.stopPropagation()
                      onArchive(s)
                    }}
                  >
                    <Archive size={12} />
                  </button>
                  {/* F-B8 要求「新建/重命名/归档/**删除**」四件套齐全。
                      后端 DELETE /api/chat/sessions/{id} 与 useChat.deleteSession
                      早就实现好了，但这里一直没渲染按钮——spec 标了 ✅ 而用户根本删不掉。 */}
                  <button
                    type="button"
                    title="删除"
                    className="danger"
                    onClick={(e) => {
                      e.stopPropagation()
                      onDelete(s)
                    }}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>

      <div style={{ padding: '10px 12px', borderTop: '1px solid var(--line-soft)' }} className="row">
        <Chip tone="accent" style={{ flex: 1 }} onClick={onOpenProfile} title="查看画像">
          <i className={`live-dot ${profileInjected ? '' : 'warn'}`} />
          {profileInjected ? `画像注入中 · ${profileName ?? ''}` : '通用模式 · 未注入画像'}
        </Chip>
      </div>
    </aside>
  )
}

export default SessionList
