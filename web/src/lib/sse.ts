/* =============================================================================
   Atelier · 对话 SSE 客户端（SPEC-03 §3.3 / PRD F-B6）

   两条通道，都是**真流式**（服务端从内存队列推，不是轮询文件）：

   1. `postTurnStream`  —— POST /api/chat/stream 开一轮。
      EventSource 只支持 GET，起轮次必须用 fetch + ReadableStream 手动解 SSE 帧。
      409 SessionBusy 会以 ApiError 抛给调用方（前端据此自动开新会话）。
   2. `openTurnStream`  —— GET /api/chat/turn/{id}/stream，**EventSource** + 指数退避
      重连（0.5s → 1s → 2s → 4s，最多 5 次）。断网恢复走这条。

   重连成功后回调 `onReconnected`，由上层去 `GET /api/chat/turn/{id}` 拉全量事件补齐，
   用 `createDeduper()` 按 `turn_id + data.index` 去重——**不重复渲染，也不丢内容**。
   ========================================================================== */

import { ApiError } from './api'
import type { TurnEvent } from './types'

/** 断线重连退避：0.5s / 1s / 2s / 4s（SPEC-03 §3.3） */
export const RECONNECT_DELAYS_MS: readonly number[] = [500, 1000, 2000, 4000]

/** 最多重连 5 次 */
export const MAX_RECONNECTS = 5

/** 终态事件：收到就收流（error 之后还有一条 done，两者都会到） */
const TERMINAL: readonly string[] = ['done', 'error']

/* -------------------------------------------------------------------------- */
/* 去重（F-B6）                                                              */
/* -------------------------------------------------------------------------- */

export type Deduper = {
  /** 该事件是否第一次出现；重复的返回 false（上层据此跳过渲染） */
  accept: (ev: TurnEvent) => boolean
  /** 已接受的事件数 */
  size: () => number
  reset: () => void
}

/** 按 `turn_id + data.index` 去重。断线重连后补齐的历史事件靠它挡掉重复渲染。 */
export function createDeduper(): Deduper {
  const seen = new Set<string>()
  return {
    accept(ev) {
      const key = `${ev.turn_id}#${Number(ev.data?.index ?? -1)}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    },
    size: () => seen.size,
    reset: () => seen.clear(),
  }
}

/* -------------------------------------------------------------------------- */
/* SSE 帧解析（纯函数，好测）                                                  */
/* -------------------------------------------------------------------------- */

export type ParsedChunk = { events: TurnEvent[]; rest: string }

/** 解析一段 SSE 文本 → 事件 + 未成帧的尾巴。

 * 帧之间以空行分隔；`: xxx` 是注释帧（保活）直接忽略；`data:` 逐行拼接后 JSON.parse。
 * 解析不了的帧不抛——断线重连时宁可少一帧也不能让整条流崩掉（上层还能靠 /turn 补齐）。
 */
export function parseSse(text: string): ParsedChunk {
  const events: TurnEvent[] = []
  const frames = text.split(/\r?\n\r?\n/)
  const rest = frames.pop() ?? ''
  for (const frame of frames) {
    const data: string[] = []
    for (const line of frame.split(/\r?\n/)) {
      if (!line || line.startsWith(':')) continue
      if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
    }
    if (!data.length) continue
    try {
      events.push(JSON.parse(data.join('\n')) as TurnEvent)
    } catch {
      /* 坏帧跳过 */
    }
  }
  return { events, rest }
}

/* -------------------------------------------------------------------------- */
/* 通道 1：POST 开一轮                                                        */
/* -------------------------------------------------------------------------- */

export type PostStreamOptions = {
  url: string
  body: unknown
  onEvent: (ev: TurnEvent) => void
  /** 响应头里就带上了 turn_id（中断要用真 id，不能用前端占位） */
  onStart?: (turnId: string | null) => void
  /** 收到 done/error 时调用，参数是 turn_id */
  onDone?: (turnId: string | null) => void
  /** HTTP 层失败（409 / 500 等）→ 抛 ApiError 让调用方处理 */
  onHttpError: (err: ApiError) => void
  /** 流已经开了、但中途断掉（网络/代理掐了）→ 调用方用 openTurnStream 接管 */
  onTransportError?: (turnId: string | null) => void
  signal?: AbortSignal
}

function apiErrorFrom(status: number, body: unknown, fallback: string): ApiError {
  const e = (body ?? {}) as { error?: { code?: string; message?: string; detail?: unknown; hint?: string } }
  return new ApiError(
    e?.error?.code ?? `HTTP${status}`,
    status,
    e?.error?.message ?? fallback,
    e?.error?.detail,
    e?.error?.hint,
  )
}

/** POST 起一轮并消费 SSE。返回清理函数。 */
export async function postTurnStream(opts: PostStreamOptions): Promise<() => void> {
  const controller = new AbortController()
  opts.signal?.addEventListener('abort', () => controller.abort())
  try {
    const res = await fetch(opts.url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts.body),
      signal: controller.signal,
    })
    if (!res.ok) {
      let body: unknown = null
      try {
        body = await res.json()
      } catch {
        /* 非 JSON 错误体 */
      }
      opts.onHttpError(apiErrorFrom(res.status, body, `请求失败（HTTP ${res.status}）`))
      return () => controller.abort()
    }
    const turnId = res.headers.get('x-atelier-turn-id')
    opts.onStart?.(turnId)
    await consumeBody(res, turnId, opts)
    return () => controller.abort()
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') return () => undefined
    // 连响应头都没拿到：这一轮根本没开起来，交给调用方按普通错误处理
    opts.onHttpError(
      new ApiError('NetworkError', 0, '连不上本地服务', undefined, '确认后端已在 127.0.0.1:8000 运行'),
    )
    return () => controller.abort()
  }
}

async function consumeBody(res: Response, turnId: string | null, opts: PostStreamOptions): Promise<void> {
  const body = res.body
  if (!body) {
    opts.onDone?.(turnId)
    return
  }
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let finished = false
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const { events, rest } = parseSse(buf)
      buf = rest
      for (const ev of events) {
        opts.onEvent(ev)
        if (TERMINAL.includes(ev.type)) finished = true
      }
      if (finished) break
    }
  } catch {
    // 流开了但中途断了：这一轮还在服务端跑，改走 EventSource 重连（F-B6）
    opts.onTransportError?.(turnId)
    return
  }
  if (!finished) opts.onTransportError?.(turnId)
  else opts.onDone?.(turnId)
}

/* -------------------------------------------------------------------------- */
/* 通道 2：EventSource 重连                                                   */
/* -------------------------------------------------------------------------- */

export type OpenStreamOptions = {
  turnId: string
  onEvent: (ev: TurnEvent) => void
  /** 每次（重）连上都会调用；attempt>0 表示这是重连 */
  onOpen?: (attempt: number) => void
  /** 退避重连 5 次仍失败 */
  onGiveUp?: (attempts: number) => void
}

/** 打开（或重连）一轮的 SSE。返回关闭函数。 */
export function openTurnStream(opts: OpenStreamOptions): () => void {
  let es: EventSource | null = null
  let timer: ReturnType<typeof setTimeout> | null = null
  let attempt = 0
  let closed = false

  const connect = () => {
    if (closed) return
    es = new EventSource(`/api/chat/turn/${encodeURIComponent(opts.turnId)}/stream`)
    es.onopen = () => {
      opts.onOpen?.(attempt)
      attempt = 0
    }
    es.onmessage = (e: MessageEvent<string>) => {
      let ev: TurnEvent
      try {
        ev = JSON.parse(e.data) as TurnEvent
      } catch {
        return
      }
      opts.onEvent(ev)
      if (TERMINAL.includes(ev.type)) close()
    }
    es.onerror = () => {
      es?.close()
      es = null
      if (closed) return
      if (attempt >= MAX_RECONNECTS) {
        opts.onGiveUp?.(attempt)
        return
      }
      const delay = RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)]
      attempt += 1
      timer = setTimeout(connect, delay)
    }
  }

  const close = () => {
    closed = true
    if (timer) clearTimeout(timer)
    es?.close()
    es = null
  }

  connect()
  return close
}

/* -------------------------------------------------------------------------- */
/* 断线补齐：拉全量事件                                                       */
/* -------------------------------------------------------------------------- */

export type TurnSnapshot = { turn_id: string; status: string; count: number; events: TurnEvent[] }

/** `GET /api/chat/turn/{id}` —— 重连成功后拉全量事件补齐（SPEC-03 §3.3）。 */
export async function fetchTurn(turnId: string): Promise<TurnSnapshot> {
  const res = await fetch(`/api/chat/turn/${encodeURIComponent(turnId)}`, { headers: { Accept: 'application/json' } })
  if (!res.ok) throw apiErrorFrom(res.status, await res.json().catch(() => null), '取这一轮的事件失败')
  return (await res.json()) as TurnSnapshot
}
