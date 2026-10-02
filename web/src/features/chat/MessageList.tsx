import { useEffect, useRef } from 'react'
import { EmptyState, Skeleton } from '@/components'
import { MessageBubble } from './MessageBubble'
import { SceneSuggestions } from './SceneSuggestions'
import type { ChatMessage } from './types'

export type MessageListProps = {
  messages: ChatMessage[]
  streamingId: string | null
  loading?: boolean
  profileName?: string | null
  onAnswer: (questionId: string, optionKey: string, label: string) => void
  onPickScene: (text: string) => void
}

/** 消息流：滚动到底；空态给 4 个场景卡（PRD F-B10） */
export function MessageList({
  messages,
  streamingId,
  loading = false,
  profileName,
  onAnswer,
  onPickScene,
}: MessageListProps) {
  const boxRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // 生成中持续贴底；用户主动往上翻时不抢滚动
  useEffect(() => {
    const box = boxRef.current
    if (!box) return
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 220
    const bottom = bottomRef.current
    if (nearBottom && bottom && typeof bottom.scrollIntoView === 'function') bottom.scrollIntoView({ block: 'end' })
  }, [messages])

  return (
    <div className="msgs" ref={boxRef}>
      <div className="msgs-in">
        {loading ? (
          <div className="stack" style={{ gap: 12 }}>
            <Skeleton height={54} radius={12} width="62%" />
            <Skeleton height={120} radius={12} />
          </div>
        ) : null}

        {!loading && messages.length === 0 ? (
          <EmptyState
            title="新会话 · 说清楚你要什么"
            description={
              <>
                当前画像「{profileName ?? '未选择（通用模式）'}」
                {profileName ? '已注入' : '不注入'}。发一条消息试试，流式输出、思考过程、门禁结果都会出现在这里。
              </>
            }
            action={<SceneSuggestions onPick={onPickScene} />}
          />
        ) : null}

        {messages.map((m) => (
          <MessageBubble
            key={m.id}
            message={m}
            streaming={m.id === streamingId}
            onAnswer={onAnswer}
            profileName={profileName}
          />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

export default MessageList
