import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from '@/components'
import { useAtelier } from '@/lib/store'
import type { Attachment, Session } from '@/lib/types'
import { Composer } from './Composer'
import { MessageList } from './MessageList'
import { SessionList } from './SessionList'
import { useChat } from './useChat'

/**
 * 对话工作台（SPEC-03 §6 / 原型 #v-chat）。
 *
 * 页面只做编排：左侧会话栏 + 中间消息流 + 底部输入框，流式状态全在 useChat 里。
 * 三条硬验收的界面表现：
 * - 断线不丢：重连后自动补齐，界面不重复渲染
 * - 2s 内停止：生成中「停止生成」替换发送按钮（UI-SPEC 规则 5）
 * - 问答题不重复：答过的卡片折叠成「已确认 + 你的选择」
 */
export function ChatPage() {
  const navigate = useNavigate()
  const profile = useAtelier((s) => s.profile)
  const draft = useAtelier((s) => s.draftPrompt)
  const draftSeq = useAtelier((s) => s.draftSeq)
  const fillPrompt = useAtelier((s) => s.fillPrompt)
  const setSessionId = useAtelier((s) => s.setSessionId)

  const [text, setText] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const booted = useRef(false)

  const onSessionBusy = useCallback(() => {
    toast.warn('该会话正在其他窗口生成，已开新会话')
  }, [])

  const chat = useChat({ onSessionBusy })
  const { state, status, send, stop, answer, uploadFiles, bootstrap } = chat

  // 能力卡 / 热点「做成内容」填入后自动聚焦（**不自动发送**，UI-SPEC 规则 1）
  useEffect(() => {
    if (draft) setText(draft)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftSeq])

  useEffect(() => {
    if (booted.current) return
    booted.current = true
    void bootstrap()
  }, [bootstrap])

  useEffect(() => {
    setSessionId(state.sessionId)
  }, [setSessionId, state.sessionId])

  const onSend = useCallback(async () => {
    const body = text.trim()
    if (!body && !attachments.length) return
    setText('')
    const atts = attachments
    setAttachments([])
    await send(body, atts)
  }, [attachments, send, text])

  const onPickFiles = useCallback(
    async (files: File[]) => {
      if (!state.sessionId) {
        await chat.newSession()
        return
      }
      try {
        const uploaded = await uploadFiles(state.sessionId, files)
        setAttachments((prev) => [...prev, ...uploaded])
      } catch (err) {
        toast.error((err as Error).message)
      }
    },
    [chat, state.sessionId, uploadFiles],
  )

  const onRename = useCallback(
    async (s: Session) => {
      const title = window.prompt('重命名会话', s.title)
      if (title == null || !title.trim()) return
      await chat.renameSession(s.id, title.trim())
    },
    [chat],
  )

  const onArchive = useCallback(
    async (s: Session) => {
      await chat.archiveSession(s.id)
      toast.ok(`已归档「${s.title}」`)
      if (s.id !== state.sessionId) return
      // 归档的是当前会话 → 顺带切到另一个，否则会停在一个已归档的会话里
      const rest = chat.state.sessions.filter((x) => x.id !== s.id && !x.archived)
      if (rest.length) await chat.selectSession(rest[0].id)
      else await chat.newSession()
    },
    [chat, state.sessionId],
  )

  return (
    <div className="chat-wrap">
      <SessionList
        groups={state.groups}
        activeId={state.sessionId}
        profileName={profile?.name ?? null}
        profileInjected={Boolean(profile && !profile.generalMode)}
        onSelect={(id) => void chat.selectSession(id)}
        onNew={() => void chat.newSession()}
        onRename={(s) => void onRename(s)}
        onArchive={(s) => void onArchive(s)}
        onOpenProfile={() => navigate('/profile')}
      />

      <div className="chat-main">
        <MessageList
          messages={state.messages}
          streamingId={chat.streamingId}
          loading={state.loading}
          profileName={profile?.name ?? null}
          onAnswer={(qid, key, label) => void answer(qid, key, label)}
          onPickScene={(t) => {
            setText(t)
            fillPrompt(t)
          }}
        />

        <Composer
          value={text}
          onChange={setText}
          onSend={() => void onSend()}
          onStop={() => void stop()}
          streaming={status === 'streaming'}
          lastEventAt={state.lastEventAt}
          reconnecting={state.reconnecting}
          attachments={attachments}
          onPickFiles={(files) => void onPickFiles(files)}
          onRemoveAttachment={(id) => setAttachments((prev) => prev.filter((a) => a.id !== id))}
        />
      </div>
    </div>
  )
}

export default ChatPage
