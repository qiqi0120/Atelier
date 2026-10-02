/* =============================================================================
   对话工作台的视图模型（把后端事件流收敛成「一条消息 = 一个气泡」）

   后端 SPEC-01 §3 的事件是**增量**的（text_delta / thinking_delta …），
   前端把它们累积成一条 assistant 消息。消息列表因此是纯展示结构，
   落库形态仍以服务端的 messages 表为准。
   ========================================================================== */

import type { Attachment, GateReport, Message, Session } from '@/lib/types'

export type TurnStatus = 'streaming' | 'done' | 'interrupted' | 'error'

export type QuestionOption = { key: string; label: string }

export type QuestionView = {
  question_id: string
  /** 属于哪一轮（刷新后重建卡片时用来挂回原消息） */
  turn_id?: string | null
  text: string
  options: QuestionOption[]
  multiple: boolean
  /** 已答就锁定：卡片折叠成「已确认 + 你的选择」，本会话不再出现（F-B7 / UI-SPEC 规则 7） */
  answered: { option_key: string; label: string } | null
}

export type ArtifactView = {
  path: string
  kind: string
  name?: string
  label?: string
  size?: number
}

export type ChatError = { code: string; message: string; hint?: string | null }

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  text: string
  /** 思考过程（折叠块内容） */
  thinking: string
  /** 思考耗时（ms），结束后才有值 */
  thinkingMs: number | null
  thinkingDone: boolean
  /** 思考开始的时刻（回放时来自事件里的 at，所以刷新后耗时也准） */
  thinkingStartAt: number | null
  attachments: Attachment[]
  artifacts: ArtifactView[]
  gate: GateReport | null
  questions: QuestionView[]
  status: TurnStatus
  error: ChatError | null
  turnId: string | null
  createdAt: string
}

export type SessionGroup = { key: string; label: string; items: Session[] }

export type ChatState = {
  sessions: Session[]
  groups: SessionGroup[]
  sessionId: string | null
  messages: ChatMessage[]
  /** 正在生成的那一轮（turn_id + 对应消息 id） */
  turnId: string | null
  /** 打字机待写出的字符（每帧 ≤4 字，超长块分帧；历史回放不经过这里） */
  pending: string
  /** 最近一次收到事件的时刻（心跳提示用） */
  lastEventAt: number
  sending: boolean
  loading: boolean
  reconnecting: boolean
}

export const emptyState: ChatState = {
  sessions: [],
  groups: [],
  sessionId: null,
  messages: [],
  turnId: null,
  pending: '',
  lastEventAt: 0,
  sending: false,
  loading: false,
  reconnecting: false,
}

/** 服务端 message → 视图消息（历史回放，**不打字机**） */
export function fromHistory(m: Message): ChatMessage {
  return {
    id: m.id,
    role: m.role === 'user' ? 'user' : 'assistant',
    text: m.text,
    thinking: '',
    thinkingMs: null,
    thinkingDone: true,
    thinkingStartAt: null,
    attachments: m.attachments ?? [],
    artifacts: [],
    gate: m.gate_report ?? null,
    questions: [],
    status: 'done',
    error: null,
    turnId: m.turn_id,
    createdAt: m.created_at,
  }
}

export function userMessage(id: string, text: string, attachments: Attachment[] = []): ChatMessage {
  return {
    id,
    role: 'user',
    text,
    thinking: '',
    thinkingMs: null,
    thinkingDone: true,
    thinkingStartAt: null,
    attachments,
    artifacts: [],
    gate: null,
    questions: [],
    status: 'done',
    error: null,
    turnId: null,
    createdAt: new Date().toISOString(),
  }
}
