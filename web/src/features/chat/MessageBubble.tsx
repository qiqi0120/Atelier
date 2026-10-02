import { AlertTriangle, Check, PauseCircle } from 'lucide-react'
import { Chip } from '@/components'
import type { Attachment } from '@/lib/types'
import { ArtifactCard } from './ArtifactCard'
import { GateBlock } from './GateBlock'
import { QuestionCard } from './QuestionCard'
import { ThinkingBlock } from './ThinkingBlock'
import type { ChatMessage } from './types'

export type MessageBubbleProps = {
  message: ChatMessage
  /** 正在流式输出的那条（显示光标） */
  streaming?: boolean
  onAnswer: (questionId: string, optionKey: string, label: string) => void
  profileName?: string | null
}

function kindText(a: Attachment): string {
  const ext = a.name.split('.').pop() ?? ''
  return ext.slice(0, 3).toUpperCase() || 'FILE'
}

/**
 * 一条消息一个气泡（原型 #v-chat 的 .msg.u / .msg.a）。
 *
 * F-B3：用户气泡**只显示实际输入的文字**，附件单独以 chip 挂在下方，绝不把文件名
 * 拼进正文。assistant 气泡按事件累积渲染四类内容：思考块 / 正文 / 产物卡 / 问答题。
 */
/** 把 ISO 时间戳显示成 HH:MM；无效值回退为空串（不要把原始串糊到界面上）。 */
function formatTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

export function MessageBubble({ message, streaming = false, onAnswer, profileName }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  return (
    <div className={`msg ${isUser ? 'u' : 'a'}`}>
      <div className="who">{isUser ? '我' : 'AI'}</div>
      <div className="bd">
        <div className="nm">
          {isUser ? '你' : 'Atelier'}
          {isUser && profileName ? (
            <Chip tone="outline" mono xs>
              {profileName}
            </Chip>
          ) : null}
          {!isUser && message.status === 'interrupted' ? (
            <Chip tone="warn" xs icon={<PauseCircle size={11} />}>
              已停止 · 内容已保留
            </Chip>
          ) : null}
          {!isUser && message.status === 'done' ? (
            <span
              className="mut2"
              title={message.turnId ? `turn_id: ${message.turnId}` : undefined}
            >
              {formatTime(message.createdAt)}
            </span>
          ) : null}
        </div>

        {isUser ? (
          <div className="bubble">
            {message.text}
            {message.attachments.length ? (
              <div className="att" style={{ marginTop: 9, marginBottom: 0 }}>
                {message.attachments.map((a) => (
                  <span className="f" key={a.id} title={a.path}>
                    <i className="th">{kindText(a)}</i>
                    {a.name}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <>
            <ThinkingBlock text={message.thinking} ms={message.thinkingMs} done={message.thinkingDone} />
            <div className="bubble">
              {message.text ? (
                message.text
              ) : streaming ? (
                <span className="typing">
                  <i className="d" />
                  <i className="d" />
                  <i className="d" />
                </span>
              ) : null}
              {streaming ? <i className="caret" /> : null}

              {message.error ? (
                <div className="gate" style={{ marginTop: message.text ? 9 : 0 }}>
                  <div className="gh">
                    <AlertTriangle size={13} />
                    {message.error.message}
                  </div>
                  <div className="gi">
                    <span className="mono">{message.error.code}</span>
                    <span className="s block">{message.error.hint ?? '已生成的部分不会丢'}</span>
                  </div>
                </div>
              ) : null}

              {message.artifacts.length ? <ArtifactCard artifacts={message.artifacts} /> : null}
              {message.gate ? <GateBlock report={message.gate} /> : null}
              {message.questions.map((q) => (
                <QuestionCard key={q.question_id} question={q} onAnswer={onAnswer} />
              ))}

              {message.status === 'interrupted' ? (
                <div className="qdone" style={{ marginTop: 8 }}>
                  <Check size={13} />
                  已停止 · 上面这些内容都还在
                </div>
              ) : null}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default MessageBubble
