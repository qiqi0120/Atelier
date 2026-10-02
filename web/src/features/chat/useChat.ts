/* =============================================================================
   对话工作台的流式状态机（SPEC-03 §6）

   `useReducer` 管全部流式状态：增量事件累积成一条 assistant 消息，
   打字机按「每帧 ≤4 字」把长块分帧写出（**不**做二次逐字动画，后端已经是增量了），
   历史回放直接铺文本、不重播打字机（F-B4）。

   三条硬验收的落点：
   - 断线不丢：``onTransportError`` → ``openTurnStream`` 指数退避重连 →
     ``fetchTurn`` 拉全量 → 同一个 deduper 按 index 去重补齐（F-B6）
   - 2s 内停止：``stop()`` 打 ``/chat/interrupt``，返回即本地收尾（不等事件）→ 立刻停打字（F-B5）
   - 问答题不重复：``question/answered`` 后该卡片锁定，且服务端不再下发（F-B7）
   ========================================================================== */

import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react'
import { ApiError, request } from '@/lib/api'
import { createDeduper, fetchTurn, openTurnStream, postTurnStream } from '@/lib/sse'
import type { Attachment, EventType, GateReport, Message, Session, TurnEvent } from '@/lib/types'
import {
  type ArtifactView,
  type ChatMessage,
  type ChatState,
  type QuestionView,
  emptyState,
  fromHistory,
  userMessage,
} from './types'

/** 每帧最多追加几个字（SPEC-03 §6「每帧 ≤ 4 字」） */
export const FRAME_CHARS = 4

type Action =
  | { type: 'sessions/loaded'; sessions: Session[]; groups: ChatState['groups'] }
  | { type: 'session/created'; session: Session }
  | { type: 'session/removed'; id: string }
  | { type: 'session/updated'; session: Session }
  | { type: 'messages/loading'; sessionId: string }
  | { type: 'messages/loaded'; sessionId: string; messages: Message[]; questions: QuestionView[] }
  | { type: 'user/sent'; message: ChatMessage; messageId: string }
  | { type: 'turn/start'; messageId: string }
  | { type: 'turn/bound'; turnId: string }
  | { type: 'turn/event'; event: TurnEvent; now: number }
  | { type: 'turn/flush' }
  | { type: 'turn/finished'; status: 'done' | 'interrupted' | 'error' }
  | { type: 'turn/reconnecting'; on: boolean }
  | { type: 'question/answered'; questionId: string; optionKey: string; label: string; message: ChatMessage }
  | { type: 'reset' }

function lastStreaming(messages: ChatMessage[]): ChatMessage | undefined {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].status === 'streaming') return messages[i]
  }
  return undefined
}

function patchStreaming(messages: ChatMessage[], fn: (m: ChatMessage) => ChatMessage): ChatMessage[] {
  return messages.map((m) => (m.status === 'streaming' ? fn(m) : m))
}

function blankAssistant(id: string, turnId: string | null, now: number): ChatMessage {
  return {
    id,
    role: 'assistant',
    text: '',
    thinking: '',
    thinkingMs: null,
    thinkingDone: false,
    thinkingStartAt: null,
    attachments: [],
    artifacts: [],
    gate: null,
    questions: [],
    status: 'streaming',
    error: null,
    turnId,
    createdAt: new Date(now).toISOString(),
  }
}

function asGate(data: Record<string, unknown>): GateReport {
  const src = (data.report as GateReport | undefined) ?? (data as unknown as GateReport)
  return { items: src.items ?? [], blocked: Boolean(src.blocked) }
}

function asArtifacts(data: Record<string, unknown>): ArtifactView[] {
  const many = Array.isArray(data.paths) ? (data.paths as string[]) : []
  const one = typeof data.path === 'string' ? [data.path] : []
  return [...one, ...many].map((path) => ({
    path,
    kind: String(data.kind ?? 'doc'),
    name: typeof data.name === 'string' ? data.name : undefined,
    label: typeof data.label === 'string' ? data.label : undefined,
    size: typeof data.size === 'number' ? data.size : undefined,
  }))
}

export function reducer(state: ChatState, action: Action): ChatState {
  switch (action.type) {
    case 'sessions/loaded':
      return { ...state, sessions: action.sessions, groups: action.groups, loading: false }

    case 'session/created':
      return { ...state, sessions: [action.session, ...state.sessions], sessionId: action.session.id }

    case 'session/removed':
      return {
        ...state,
        sessions: state.sessions.filter((s) => s.id !== action.id),
        groups: state.groups
          .map((g) => ({ ...g, items: g.items.filter((s) => s.id !== action.id) }))
          .filter((g) => g.items.length > 0),
        sessionId: state.sessionId === action.id ? null : state.sessionId,
        messages: state.sessionId === action.id ? [] : state.messages,
      }

    case 'session/updated': {
      const sessions = state.sessions.map((s) => (s.id === action.session.id ? action.session : s))
      return { ...state, sessions, groups: regroup(sessions) }
    }

    case 'messages/loading':
      return { ...state, loading: true, messages: [], sessionId: action.sessionId, turnId: null, pending: '' }

    case 'messages/loaded': {
      if (state.sessionId !== action.sessionId) return state
      const history = action.messages.map(fromHistory)
      // 已答的问答题在刷新后仍是「已确认」态（F-B7 跨刷新成立）
      return {
        ...state,
        loading: false,
        messages: applyAnswered(history, action.questions),
      }
    }

    case 'user/sent':
      return {
        ...state,
        messages: [...state.messages, action.message, blankAssistant(action.messageId, null, Date.now())],
        turnId: null,
        pending: '',
        sending: true,
      }

    case 'turn/start':
      return {
        ...state,
        messages: [...state.messages, blankAssistant(action.messageId, null, Date.now())],
        sending: true,
        pending: '',
      }

    case 'turn/bound':
      // 服务端响应头里带了真 turn_id：绑上它，「停止生成」才不会打错 id
      if (state.turnId === action.turnId) return state
      return {
        ...state,
        turnId: action.turnId,
        messages: patchStreaming(state.messages, (m) => ({ ...m, turnId: action.turnId })),
      }

    case 'turn/event': {
      const ev = action.event
      const d = (ev.data ?? {}) as Record<string, unknown>
      const has = lastStreaming(state.messages)
      const base: ChatMessage[] = has ? state.messages : [...state.messages, blankAssistant(nextId('a'), ev.turn_id, action.now)]
      const next = patchStreaming(base, (m) => ({ ...m, turnId: ev.turn_id }))
      const type = ev.type as EventType
      let pending = state.pending
      const messages = patchStreaming(next, (m): ChatMessage => {
        switch (type) {
          case 'thinking_start':
            return {
              ...m,
              thinking: '',
              thinkingMs: null,
              thinkingDone: false,
              thinkingStartAt: typeof d.at === 'number' ? d.at * 1000 : action.now,
            }
          case 'thinking_delta': {
            if (d.phase === 'end') {
              const end = typeof d.at === 'number' ? d.at * 1000 : action.now
              return { ...m, thinkingDone: true, thinkingMs: Math.max(0, Math.round(end - (m.thinkingStartAt ?? end))) }
            }
            return { ...m, thinking: m.thinking + String(d.text ?? '') }
          }
          case 'text_delta':
            // F-B4：直接进待写队列，由 rAF 每帧 ≤4 字写出（超长块分帧）
            pending += String(d.text ?? '')
            return m
          case 'question': {
            const q: QuestionView = {
              question_id: String(d.question_id ?? `${ev.turn_id}:q${m.questions.length}`),
              text: String(d.text ?? ''),
              options: (d.options as QuestionView['options']) ?? [],
              multiple: Boolean(d.multiple),
              answered: null,
            }
            if (m.questions.some((x) => x.question_id === q.question_id)) return m
            return { ...m, questions: [...m.questions, q] }
          }
          case 'artifact':
            return { ...m, artifacts: [...m.artifacts, ...asArtifacts(d)] }
          case 'gate_result':
            return { ...m, gate: asGate(d) }
          case 'error':
            return {
              ...m,
              error: {
                code: String(d.code ?? 'Error'),
                message: String(d.message ?? '生成失败'),
                hint: (d.hint as string | null) ?? null,
              },
            }
          case 'done': {
            const interrupted = Boolean(d.interrupted)
            const failed = Boolean(d.failed)
            const full = typeof d.text === 'string' ? d.text : m.text
            return {
              ...m,
              text: pending ? m.text + pending : full,
              status: interrupted ? 'interrupted' : failed ? 'error' : 'done',
              thinkingDone: true,
            }
          }
          default:
            return m
        }
      })
      return { ...state, messages, pending: type === 'done' ? '' : pending, lastEventAt: action.now }
    }

    case 'turn/flush': {
      if (!state.pending) return state
      const take = state.pending.slice(0, FRAME_CHARS)
      return {
        ...state,
        pending: state.pending.slice(FRAME_CHARS),
        messages: patchStreaming(state.messages, (m) => ({ ...m, text: m.text + take })),
      }
    }

    case 'turn/finished': {
      // 待写出的字符直接补进正文再收尾：用户不丢已生成内容（F-B5）
      const tail = state.pending
      const messages = state.messages.map((m) =>
        m.status === 'streaming' ? { ...m, text: tail ? m.text + tail : m.text, status: action.status } : m,
      )
      return { ...state, messages, turnId: null, pending: '', sending: false, reconnecting: false }
    }

    case 'turn/reconnecting':
      return { ...state, reconnecting: action.on }

    case 'question/answered': {
      const messages = state.messages.map((m) => ({
        ...m,
        questions: m.questions.map((q) =>
          q.question_id === action.questionId
            ? { ...q, answered: { option_key: action.optionKey, label: action.label } }
            : q,
        ),
      }))
      return { ...state, messages: [...messages, action.message] }
    }

    case 'reset':
      // 保留会话列表与当前会话（切会话/开新会话都只是清消息流）
      return { ...emptyState, sessions: state.sessions, groups: state.groups, sessionId: state.sessionId }

    default:
      return state
  }
}

function regroup(sessions: Session[]): ChatState['groups'] {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const yesterday = today - 86400000
  const buckets: ChatState['groups'] = [
    { key: 'today', label: '今天', items: [] },
    { key: 'yesterday', label: '昨天', items: [] },
    { key: 'earlier', label: '更早', items: [] },
    { key: 'archived', label: '已归档', items: [] },
  ]
  for (const s of sessions) {
    if (s.archived) {
      buckets[3].items.push(s)
      continue
    }
    const t = new Date(s.updated_at).getTime()
    if (t >= today) buckets[0].items.push(s)
    else if (t >= yesterday) buckets[1].items.push(s)
    else buckets[2].items.push(s)
  }
  return buckets.filter((b) => b.items.length > 0)
}

function applyAnswered(messages: ChatMessage[], questions: QuestionView[]): ChatMessage[] {
  if (!questions.length) return messages
  const byTurn = new Map<string, QuestionView[]>()
  for (const q of questions) {
    if (!q.answered) continue
    const list = byTurn.get(q.turn_id ?? '') ?? []
    list.push(q)
    byTurn.set(q.turn_id ?? '', list)
  }
  return messages.map((m) => {
    const qs = byTurn.get(m.turnId ?? '')
    if (!qs?.length) return m
    return { ...m, questions: [...m.questions, ...qs.filter((q) => !m.questions.some((x) => x.question_id === q.question_id))] }
  })
}

type SessionListResponse = { sessions: Session[]; groups: ChatState['groups'] }
type MessagesResponse = { items: Message[]; questions: QuestionView[] }

let localId = 0
const nextId = (p: string) => `${p}_${Date.now().toString(36)}${(localId += 1).toString(36)}`

export function useChat(options: { onSessionBusy?: () => void } = {}) {
  const { onSessionBusy } = options
  const [state, dispatch] = useReducer(reducer, emptyState)
  const deduper = useRef(createDeduper()).current
  const closeStream = useRef<(() => void) | null>(null)
  const clientId = useRef(nextId('win')).current

  /* ---- 打字机：rAF 每帧 ≤4 字（历史回放不经过这里） ---- */
  useEffect(() => {
    if (!state.pending || !state.turnId) return
    let raf = 0
    const tick = () => {
      dispatch({ type: 'turn/flush' })
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [state.pending, state.turnId])

  useEffect(() => () => closeStream.current?.(), [])

  /* ---- 事件入口：所有通道（SSE 首连 / 重连 / 全量补齐）都走它 ---- */
  const onEvent = useCallback(
    (ev: TurnEvent) => {
      if (!deduper.accept(ev)) return
      dispatch({ type: 'turn/event', event: ev, now: Date.now() })
      if (ev.type === 'done') {
        dispatch({ type: 'turn/finished', status: ev.data?.interrupted ? 'interrupted' : ev.data?.failed ? 'error' : 'done' })
      }
    },
    [deduper],
  )

  const catchUp = useCallback(
    async (turnId: string) => {
      // 断线重连成功后拉全量补齐：重复的按 index 被 deduper 挡掉（F-B6）
      try {
        const snap = await fetchTurn(turnId)
        snap.events.forEach(onEvent)
        if (snap.status !== 'running') {
          dispatch({
            type: 'turn/finished',
            status: snap.status === 'error' ? 'error' : snap.status === 'interrupted' ? 'interrupted' : 'done',
          })
        }
      } catch {
        /* 补不齐就靠后续重连继续 */
      }
    },
    [onEvent],
  )

  const attach = useCallback(
    (turnId: string) => {
      closeStream.current?.()
      closeStream.current = openTurnStream({
        turnId,
        onEvent,
        onOpen: (attempt) => {
          dispatch({ type: 'turn/reconnecting', on: attempt > 0 })
          if (attempt > 0) void catchUp(turnId)
        },
        onGiveUp: () => {
          dispatch({ type: 'turn/reconnecting', on: false })
          dispatch({ type: 'turn/finished', status: 'error' })
        },
      })
    },
    [catchUp, onEvent],
  )

  /* ---- 会话 ---- */

  const loadSessions = useCallback(async (keepId?: string | null) => {
    const data = await request<SessionListResponse>('/chat/sessions', { handled: true })
    dispatch({ type: 'sessions/loaded', sessions: data.sessions, groups: data.groups })
    return data.sessions.find((s) => s.id === keepId) ?? data.sessions[0] ?? null
  }, [])

  const openSession = useCallback(async (sessionId: string) => {
    dispatch({ type: 'messages/loading', sessionId })
    const data = await request<MessagesResponse>(`/chat/sessions/${sessionId}/messages`, { handled: true })
    dispatch({ type: 'messages/loaded', sessionId, messages: data.items, questions: data.questions ?? [] })
  }, [])

  const newSession = useCallback(
    async (title?: string) => {
      const data = await request<{ session: Session }>('/chat/sessions', {
        method: 'POST',
        body: JSON.stringify({ title: title ?? null }),
        handled: true,
      })
      dispatch({ type: 'session/created', session: data.session })
      dispatch({ type: 'reset' })
      return data.session
    },
    [],
  )

  const selectSession = useCallback(
    async (sessionId: string) => {
      if (state.turnId) return // 生成中不切，避免把流挂到别的会话上
      await openSession(sessionId)
      await loadSessions(sessionId)
    },
    [loadSessions, openSession, state.turnId],
  )

  const renameSession = useCallback(async (sessionId: string, title: string) => {
    const data = await request<{ session: Session }>(`/chat/sessions/${sessionId}`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
      handled: true,
    })
    dispatch({ type: 'session/updated', session: data.session })
  }, [])

  const archiveSession = useCallback(async (sessionId: string) => {
    const data = await request<{ session: Session }>(`/chat/sessions/${sessionId}/archive`, {
      method: 'POST',
      handled: true,
    })
    dispatch({ type: 'session/updated', session: data.session })
    return data.session
  }, [])

  const deleteSession = useCallback(
    async (sessionId: string) => {
      // 破坏性操作：先申请 confirm token（SPEC-01 §8.1）
      const tok = await request<{ token: string }>('/chat/confirm-token', {
        method: 'POST',
        body: JSON.stringify({ action: 'delete-session', id: sessionId }),
        handled: true,
      })
      // 注意：无 body 的 DELETE 也要显式带 Content-Type，否则被跨站写中间件挡掉
      await request(`/chat/sessions/${sessionId}?confirm=${encodeURIComponent(tok.token)}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        handled: true,
      })
      dispatch({ type: 'session/removed', id: sessionId })
    },
    [],
  )

  /* ---- 素材上传（F-B2 三通道共用） ---- */

  const uploadFiles = useCallback(async (sessionId: string, files: File[]): Promise<Attachment[]> => {
    const out: Attachment[] = []
    for (const file of files) {
      const fd = new FormData()
      fd.append('session_id', sessionId)
      fd.append('file', file)
      const res = await fetch('/api/chat/upload', { method: 'POST', body: fd })
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { error?: { message?: string; hint?: string } } | null
        throw new ApiError(
          'ValidationError',
          res.status,
          body?.error?.message ?? '素材上传失败',
          undefined,
          body?.error?.hint,
        )
      }
      const att = (await res.json()) as Attachment
      out.push(att)
    }
    return out
  }, [])

  /* ---- 发消息 ---- */

  const runTurn = useCallback(
    async (sessionId: string, text: string, attachments: Attachment[]) => {
      const assistantId = nextId('a')
      dispatch({ type: 'user/sent', message: userMessage(nextId('m'), text, attachments), messageId: assistantId })
      closeStream.current?.()
      await postTurnStream({
        url: '/api/chat/stream',
        body: { session_id: sessionId, text, attachments, client_id: clientId },
        onStart: (turnId) => {
          if (turnId) dispatch({ type: 'turn/bound', turnId })
        },
        onEvent,
        // 409 = 这个会话正在别的窗口生成 → 自动开新会话并把消息带过去（F-B12）
        onHttpError: async (err) => {
          const detail = err.detail as { same_client?: boolean } | undefined
          if (err.code === 'SessionBusy' && detail?.same_client === false) {
            onSessionBusy?.()
            const fresh = await newSession()
            await runTurn(fresh.id, text, attachments)
            return
          }
          dispatch({
            type: 'turn/event',
            event: { type: 'error', turn_id: 'e', data: { code: err.code, message: err.message, hint: err.hint } },
            now: Date.now(),
          })
          dispatch({ type: 'turn/finished', status: 'error' })
        },
        // 流开了但中途断 → EventSource 退避重连 + /turn 全量补齐（F-B6）
        onTransportError: (turnId) => {
          if (turnId) attach(turnId)
          else dispatch({ type: 'turn/finished', status: 'error' })
        },
      })
    },
    [attach, clientId, newSession, onEvent, onSessionBusy],
  )

  const send = useCallback(
    async (text: string, attachments: Attachment[] = []) => {
      if (state.turnId || state.sending) return
      let sessionId = state.sessionId
      if (!sessionId) {
        const s = await newSession()
        sessionId = s.id
      }
      await runTurn(sessionId, text, attachments)
    },
    [newSession, runTurn, state.sending, state.sessionId, state.turnId],
  )

  /** 2s 内停止：接口一发回来就本地收尾，不等事件（UI-SPEC 规则 5） */
  const stop = useCallback(async () => {
    const turnId = state.turnId
    if (!turnId) return
    const t0 = Date.now()
    try {
      await request<{ interrupted: boolean }>('/chat/interrupt', {
        method: 'POST',
        body: JSON.stringify({ turn_id: turnId }),
        handled: true,
        silent: true,
      })
    } catch {
      /* 中断失败也要停：本地已经收尾，服务端下一轮自然结束 */
    }
    if (Date.now() - t0 >= 2000) console.warn('[chat] 中断超过 2s', turnId)
    dispatch({ type: 'turn/finished', status: 'interrupted' })
    closeStream.current?.()
    closeStream.current = null
    void loadSessions(state.sessionId)
  }, [loadSessions, state.sessionId, state.turnId])

  const answer = useCallback(
    async (questionId: string, optionKey: string, label: string) => {
      const sessionId = state.sessionId
      if (!sessionId) return
      // 卡片锁定 + 选项文案作为新的 user message 继续生成（F-B7）
      dispatch({ type: 'question/answered', questionId, optionKey, label, message: userMessage(nextId('m'), label) })
      dispatch({ type: 'turn/start', messageId: nextId('a') })
      closeStream.current?.()
      await postTurnStream({
        url: '/api/chat/answer',
        body: { session_id: sessionId, question_id: questionId, option_key: optionKey },
        onStart: (turnId) => {
          if (turnId) dispatch({ type: 'turn/bound', turnId })
        },
        onEvent,
        onHttpError: () => dispatch({ type: 'turn/finished', status: 'error' }),
        onTransportError: (turnId) => {
          if (turnId) attach(turnId)
          else dispatch({ type: 'turn/finished', status: 'error' })
        },
      })
    },
    [attach, onEvent, state.sessionId],
  )

  const bootstrap = useCallback(async () => {
    const first = await loadSessions(null)
    if (first) await openSession(first.id)
    else await newSession()
  }, [loadSessions, newSession, openSession])

  const streaming = useMemo(() => lastStreaming(state.messages), [state.messages])
  const status = useMemo<'idle' | 'streaming' | 'interrupted' | 'error' | 'done'>(() => {
    if (state.turnId) return 'streaming'
    if (streaming) return streaming.status === 'streaming' ? 'streaming' : streaming.status
    return 'idle'
  }, [state.turnId, streaming])

  return {
    state,
    status,
    streamingId: streaming?.id ?? null,
    send,
    stop,
    answer,
    uploadFiles,
    bootstrap,
    selectSession,
    newSession,
    renameSession,
    archiveSession,
    deleteSession,
  }
}

export type ChatApi = ReturnType<typeof useChat>
