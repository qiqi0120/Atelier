import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { useState } from 'react'
import { fireEvent, render, screen, waitFor, act, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Composer } from '@/features/chat/Composer'
import { QuestionCard } from '@/features/chat/QuestionCard'
import { HeartbeatHint } from '@/features/chat/HeartbeatHint'
import { MessageBubble } from '@/features/chat/MessageBubble'
import { ChatPage } from '@/features/chat/ChatPage'
import { emptyState, userMessage, type ChatMessage } from '@/features/chat/types'
import { FRAME_CHARS, reducer } from '@/features/chat/useChat'
import { RECONNECT_DELAYS_MS, createDeduper, parseSse } from '@/lib/sse'
import type { TurnEvent } from '@/lib/types'

/* -------------------------------------------------------------------------- */
/* 工具                                                                       */
/* -------------------------------------------------------------------------- */

function ev(type: string, turn_id: string, data: Record<string, unknown>, index: number): TurnEvent {
  return { type: type as TurnEvent['type'], turn_id, data: { ...data, index } }
}

/* jsdom 里没有 fetch/Response，这里用鸭子类型的响应桩（不依赖 undici） */
type FakeRes = {
  ok: boolean
  status: number
  headers: { get: (k: string) => string | null }
  json: () => Promise<unknown>
  text: () => Promise<string>
  body?: unknown
}

const fakeRes = (opts: { body: string; status: number; json?: unknown; contentType: string; turnId?: string }): FakeRes => ({
  ok: opts.status < 400,
  status: opts.status,
  headers: {
    get: (k: string) => (k.toLowerCase() === 'content-type' ? opts.contentType : opts.turnId ?? null),
  },
  json: async () => (opts.json ?? {}),
  text: async () => JSON.stringify(opts.json ?? {}),
  body: {
    getReader: () => {
      let sent = false
      const enc = new TextEncoder()
      return {
        read: async () =>
          sent ? { done: true, value: undefined } : ((sent = true), { done: false, value: enc.encode(opts.body) }),
        cancel: async () => undefined,
      }
    },
  },
})

const jsonRes = (body: unknown, status = 200) =>
  fakeRes({ body: '', status, json: body, contentType: 'application/json' })

const sseRes = (events: TurnEvent[], turnId: string) =>
  fakeRes({
    body: events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join(''),
    status: 200,
    contentType: 'text/event-stream',
    turnId,
  })

/* -------------------------------------------------------------------------- */
/* 1. 输入框：Enter 发送 / Shift+Enter 换行 / 粘贴素材                          */
/* -------------------------------------------------------------------------- */

describe('Composer（UI-SPEC 规则 5 / 8）', () => {
  const setup = () => {
    const props = {
      value: '',
      onChange: vi.fn(),
      onSend: vi.fn(),
      onStop: vi.fn(),
      streaming: false,
      lastEventAt: 0,
      attachments: [],
      onPickFiles: vi.fn(),
      onRemoveAttachment: vi.fn(),
    }
    const r = render(<Composer {...props} />)
    return { ...props, ...r, ta: screen.getByPlaceholderText(/说清楚你要什么/) as HTMLTextAreaElement }
  }

  it('Enter 发送、Shift+Enter 换行', () => {
    const onSend = vi.fn()
    function Harness() {
      const [v, setV] = useState('')
      return (
        <Composer
          value={v}
          onChange={setV}
          onSend={onSend}
          onStop={vi.fn()}
          streaming={false}
          lastEventAt={0}
          attachments={[]}
          onPickFiles={vi.fn()}
          onRemoveAttachment={vi.fn()}
        />
      )
    }
    render(<Harness />)
    const ta = screen.getByPlaceholderText(/说清楚你要什么/)
    fireEvent.change(ta, { target: { value: '写一篇小红书' } })
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: true })
    expect(onSend).not.toHaveBeenCalled()
    fireEvent.keyDown(ta, { key: 'Enter' })
    expect(onSend).toHaveBeenCalledTimes(1)
  })

  it('粘贴剪贴板里的图片走上传通道，不把图片当文字', () => {
    const { onPickFiles, onSend } = setup()
    const file = new File([new Uint8Array([1, 2, 3])], 'shot.png', { type: 'image/png' })
    const box = document.querySelector('.cbox') as HTMLElement
    fireEvent.paste(box, {
      clipboardData: {
        items: [
          { kind: 'file', type: 'image/png', getAsFile: () => file },
          { kind: 'string', type: 'text/plain', getAsFile: () => null },
        ],
      },
    })
    expect(onPickFiles).toHaveBeenCalledWith([file])
    expect(onSend).not.toHaveBeenCalled()
  })

  it('拖拽进入时高亮 .cbox.drag', () => {
    const { onPickFiles } = setup()
    const box = document.querySelector('.cbox') as HTMLElement
    fireEvent.dragOver(box, { dataTransfer: { files: [] } })
    expect(box.className).toContain('drag')
    const file = new File(['x'], '素材.pdf', { type: 'application/pdf' })
    fireEvent.drop(box, { dataTransfer: { files: [file] } })
    expect(onPickFiles).toHaveBeenCalledWith([file])
    expect(box.className).not.toContain('drag')
  })

  it('生成中用「停止生成」替换发送按钮', () => {
    const props = {
      value: '',
      onChange: vi.fn(),
      onSend: vi.fn(),
      onStop: vi.fn(),
      streaming: true,
      lastEventAt: Date.now(),
      attachments: [],
      onPickFiles: vi.fn(),
      onRemoveAttachment: vi.fn(),
    }
    render(<Composer {...props} />)
    expect(screen.queryByText('发送')).toBeNull()
    fireEvent.click(screen.getByText('停止生成'))
    expect(props.onStop).toHaveBeenCalled()
  })
})

/* -------------------------------------------------------------------------- */
/* 2. 问答题：点完锁定折叠为「已确认 + 你的选择」（F-B7）                        */
/* -------------------------------------------------------------------------- */

describe('QuestionCard（F-B7 / UI-SPEC 规则 7）', () => {
  const question = {
    question_id: 'q_01',
    text: '补一个信息，我出终版',
    options: [
      { key: 'A', label: '保持这个语气，直接出终版' },
      { key: 'B', label: '再狠一点，标题带争议性' },
    ],
    multiple: false,
    answered: null,
  }

  it('点选项后卡片锁定、折叠成「已确认 + 你的选择」，并回调 option_key', () => {
    const onAnswer = vi.fn()
    render(<QuestionCard question={question} onAnswer={onAnswer} />)
    fireEvent.click(screen.getByText('保持这个语气，直接出终版'))
    expect(onAnswer).toHaveBeenCalledWith('q_01', 'A', '保持这个语气，直接出终版')
    expect(screen.getByText(/已确认 · 你的选择：保持这个语气/)).toBeInTheDocument()
    // 全部锁定：另一个选项不该还能点
    expect(screen.queryByText('再狠一点，标题带争议性')).toBeNull()
  })

  it('服务端回传的已答问题直接渲染成已确认态（刷新后仍在）', () => {
    render(
      <QuestionCard
        question={{ ...question, answered: { option_key: 'B', label: '再狠一点，标题带争议性' } }}
        onAnswer={vi.fn()}
      />,
    )
    expect(screen.getByText(/已确认 · 你的选择：再狠一点/)).toBeInTheDocument()
  })
})

/* -------------------------------------------------------------------------- */
/* 3. 心跳提示：静默 30s 才出现（PRD F-B11）                                    */
/* -------------------------------------------------------------------------- */

describe('HeartbeatHint', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('刚收到事件时不提示', () => {
    render(<HeartbeatHint active lastEventAt={Date.now()} />)
    expect(screen.queryByText(/未卡住/)).toBeNull()
  })

  it('静默 30s 后提示「未卡住，继续生成中」', () => {
    const last = Date.now() - 5000
    render(<HeartbeatHint active lastEventAt={last} />)
    expect(screen.queryByText(/未卡住/)).toBeNull()
    act(() => {
      vi.advanceTimersByTime(26_000)
    })
    expect(screen.getByText(/未卡住，继续生成中/)).toBeInTheDocument()
  })

  it('不生成时不提示', () => {
    render(<HeartbeatHint active={false} lastEventAt={Date.now() - 60_000} />)
    expect(screen.queryByText(/未卡住/)).toBeNull()
  })
})

/* -------------------------------------------------------------------------- */
/* 4. 消息气泡：F-B3 消息区只显示实际输入文字                                  */
/* -------------------------------------------------------------------------- */

describe('MessageBubble（F-B3）', () => {
  const withAttachment: ChatMessage = {
    ...userMessage('m1', '按这张图改一版', [
      { id: 'a1', kind: 'image', path: 'outputs/_uploads/s1/灵感图.png', name: '灵感图.png', size: 12, mime: 'image/png' },
    ]),
  }

  it('用户气泡只显示输入文字，附件单独以 chip 挂在下方', () => {
    const { container } = render(
      <MemoryRouter>
        <MessageBubble message={withAttachment} onAnswer={vi.fn()} profileName="AI 效率观察" />
      </MemoryRouter>,
    )
    const bubble = container.querySelector('.msg.u .bubble') as HTMLElement
    expect(bubble.textContent).toContain('按这张图改一版')
    expect(bubble.textContent).not.toContain('按这张图改一版[附件]')
    // 文件名只出现在附件 chip 上，不污染正文
    const chip = container.querySelector('.msg.u .att .f') as HTMLElement
    expect(chip.textContent).toContain('灵感图.png')
    expect(bubble.querySelector('.att')).not.toBeNull()
  })

  it('assistant 气泡渲染思考块 / 产物路径 chip / 门禁逐项', () => {
    const m: ChatMessage = {
      ...userMessage('a1', ''),
      role: 'assistant',
      status: 'done',
      thinking: '1. 检索热榜 2. 匹配画像',
      thinkingMs: 1800,
      thinkingDone: true,
      text: '写好了。',
      artifacts: [{ path: 'outputs/demo/成品/card-01.png', kind: 'image' }],
      gate: {
        items: [
          { gate: 'wordcount', label: '小红书正文', severity: 'block', passed: true, actual: 782, limit: 1000, message: 'ok', fix_hint: null },
          { gate: 'ai_flavor', label: 'AI 味自检', severity: 'warn', passed: false, actual: 72, limit: 80, message: '略高', fix_hint: '再具体一点' },
        ],
        blocked: false,
      },
    }
    const { container } = render(
      <MemoryRouter>
        <MessageBubble message={m} onAnswer={vi.fn()} />
      </MemoryRouter>,
    )
    expect(container.querySelector('.think summary')?.textContent).toContain('1.8s')
    const path = container.querySelector('.artifact .path') as HTMLElement
    expect(path.textContent).toBe('outputs/demo/成品/card-01.png')
    expect(container.querySelector('.gate .gi .s.pass')?.textContent).toBe('PASS')
    expect(container.querySelector('.gate .gi .s.warn')?.textContent).toBe('WARN')
  })
})

/* -------------------------------------------------------------------------- */
/* 5. 流式状态：逐帧 ≤4 字、去重不重复渲染                                     */
/* -------------------------------------------------------------------------- */

describe('流式状态机（F-B4 / F-B6）', () => {
  const turn = 't_1'

  it('text_delta 进待写队列，每帧最多追加 4 字，最终文本与增量一致', () => {
    let s = reducer({ ...emptyState, sending: true }, { type: 'user/sent', message: userMessage('m1', 'hi'), messageId: 'a1' })
    s = reducer(s, { type: 'turn/bound', turnId: turn })
    s = reducer(s, { type: 'turn/event', event: ev('text_delta', turn, { text: '这是一段比较长的正文' }, 0), now: 1 })

    // 还没有任何字符落地：都在待写队列里（打字机还没跑帧）
    expect(s.messages[1].text).toBe('')
    expect(s.pending).toBe('这是一段比较长的正文')

    const frames: number[] = []
    while (s.pending) {
      const before = s.messages[1].text.length
      s = reducer(s, { type: 'turn/flush' })
      frames.push(s.messages[1].text.length - before)
    }
    expect(Math.max(...frames)).toBeLessThanOrEqual(FRAME_CHARS)
    expect(s.messages[1].text).toBe('这是一段比较长的正文')
  })

  it('done 之后状态收敛、待写队列清空（不留半截字）', () => {
    let s = reducer({ ...emptyState, sending: true }, { type: 'user/sent', message: userMessage('m1', 'hi'), messageId: 'a1' })
    s = reducer(s, { type: 'turn/event', event: ev('text_delta', turn, { text: '开头' }, 0), now: 1 })
    s = reducer(s, { type: 'turn/flush' })
    s = reducer(s, { type: 'turn/event', event: ev('text_delta', turn, { text: '还有半截' }, 1), now: 2 })
    s = reducer(s, { type: 'turn/event', event: ev('done', turn, { text: '开头还有半截' }, 2), now: 3 })
    s = reducer(s, { type: 'turn/finished', status: 'done' })
    expect(s.messages[1].text).toBe('开头还有半截')
    expect(s.messages[1].status).toBe('done')
    expect(s.pending).toBe('')
    expect(s.turnId).toBeNull()
  })

  it('中断时已生成内容一条不丢', () => {
    let s = reducer({ ...emptyState, sending: true }, { type: 'user/sent', message: userMessage('m1', 'hi'), messageId: 'a1' })
    s = reducer(s, { type: 'turn/event', event: ev('text_delta', turn, { text: '已经写好的半篇' }, 0), now: 1 })
    s = reducer(s, { type: 'turn/flush' })
    s = reducer(s, { type: 'turn/event', event: ev('text_delta', turn, { text: '还没写完' }, 1), now: 2 })
    s = reducer(s, { type: 'turn/finished', status: 'interrupted' })
    expect(s.messages[1].text).toBe('已经写好的半篇还没写完')
    expect(s.messages[1].status).toBe('interrupted')
  })

  it('历史回放不打字机：loaded 直接铺全文，pending 为空', () => {
    const s = reducer(
      { ...emptyState, sessionId: 's1' },
      {
        type: 'messages/loaded',
        sessionId: 's1',
        messages: [
          { id: 'm1', session_id: 's1', role: 'user', text: '问题', turn_id: null, attachments: [], gate_report: null, created_at: '' },
          { id: 'm2', session_id: 's1', role: 'assistant', text: '这是完整答案', turn_id: 't_1', attachments: [], gate_report: null, created_at: '' },
        ],
        questions: [],
      },
    )
    expect(s.messages[1].text).toBe('这是完整答案')
    expect(s.pending).toBe('')
  })
})

/* -------------------------------------------------------------------------- */
/* 6. SSE 客户端：帧解析 + 退避 + 去重                                         */
/* -------------------------------------------------------------------------- */

describe('lib/sse.ts', () => {
  it('解析多帧、忽略注释保活帧、跳过坏帧', () => {
    const text = [
      ': atelier chat stream',
      '',
      'data: {"type":"thinking_start","turn_id":"t1","data":{"index":0}}',
      '',
      'data: {"type":"text_delta","turn_id":"t1","data":{"text":"你好","index":1}}',
      '',
      'data: 不是 JSON',
      '',
      ': keep-alive',
      '',
      '',
    ].join('\n')
    const { events, rest } = parseSse(text)
    expect(events.map((e) => e.type)).toEqual(['thinking_start', 'text_delta'])
    expect(events[1].data.text).toBe('你好')
    expect(rest).toBe('')
  })

  it('未成帧的尾巴留在 rest 里等下一段', () => {
    const { events, rest } = parseSse('data: {"type":"done","turn_id":"t1","data":{}}\n\ndata: {"type":"te')
    expect(events).toHaveLength(1)
    expect(rest).toBe('data: {"type":"te')
  })

  it('退避序列是 0.5/1/2/4s，最多 5 次', () => {
    expect(RECONNECT_DELAYS_MS).toEqual([500, 1000, 2000, 4000])
  })

  it('按 turn_id + index 去重：断线重连后重复事件被挡掉', () => {
    const d = createDeduper()
    const a = ev('text_delta', 't1', { text: '你好' }, 1)
    expect(d.accept(a)).toBe(true)
    expect(d.accept({ ...a })).toBe(false) // 服务端重放同一条
    expect(d.accept(ev('text_delta', 't1', { text: '你好' }, 2))).toBe(true)
    expect(d.size()).toBe(2)
  })
})

/* -------------------------------------------------------------------------- */
/* 7. 多窗口防撞：409 → 自动开新会话并把消息带过去（F-B12）                    */
/* -------------------------------------------------------------------------- */

describe('ChatPage 冲突处理（F-B12）', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('F-B8：hover 出删除按钮，二次确认 + 逐字输入标题后才真删', async () => {
    const sessionA = { id: 's_del', title: '要删掉的会话', profile_id: null, created_at: '', updated_at: '', archived: false, last_turn_id: null }
    const calls: string[] = []

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        calls.push(`${init?.method ?? 'GET'} ${url}`)
        if (url.includes('/messages')) {
          return jsonRes({ items: [], questions: [], count: 0, total: 0, has_more: false, session_id: 's_del' })
        }
        if (url.includes('/confirm-token')) return jsonRes({ token: 'tok_1', action: 'delete-session', id: 's_del' }, 200)
        if (init?.method === 'DELETE') return jsonRes({ session_id: 's_del', removed: true }, 200)
        if (url.endsWith('/api/chat/sessions') && init?.method === 'POST') {
          return jsonRes({ session: { ...sessionA, id: 's_new', title: '新会话' } }, 200)
        }
        if (url.endsWith('/api/chat/sessions')) {
          return jsonRes({ sessions: [sessionA], groups: [{ key: 'today', label: '今天', items: [sessionA] }], count: 1 })
        }
        return jsonRes({}, 200)
      }),
    )

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>,
    )

    // 1) 列表项上真的有删除按钮（F-B8 四件套：新建/重命名/归档/删除）
    const del = await screen.findByTitle('删除')
    expect(del).toBeInTheDocument()

    // 2) 点它只弹确认框，不直接删
    fireEvent.click(del)
    await screen.findByText('删除这个会话')
    expect(calls.some((c) => c.startsWith('DELETE'))).toBe(false)

    // 3) 确认按钮要逐字输入标题才解锁（ConfirmDialog requireTyping）
    //    页面里有两个 textbox（底部输入框 + 对话框的逐字输入框），必须限定在对话框内查
    const dlg = await screen.findByRole('dialog')
    const okBtn = within(dlg).getByRole('button', { name: /确认删除/ })
    expect(okBtn).toBeDisabled()
    fireEvent.change(within(dlg).getByRole('textbox'), { target: { value: '要删掉的会话' } })
    await waitFor(() => expect(within(dlg).getByRole('button', { name: /确认删除/ })).toBeEnabled())
    fireEvent.click(within(dlg).getByRole('button', { name: /确认删除/ }))

    // 4) 真的发了 DELETE，且带 confirm token
    await waitFor(() => expect(calls.some((c) => c.startsWith('DELETE'))).toBe(true))
    expect(calls.find((c) => c.startsWith('DELETE'))).toContain('confirm=tok_1')
  })

  it('第二个窗口撞上 409 时自动新建会话并重发', async () => {
    const calls: { url: string; body: unknown }[] = []
    const sessionA = { id: 's_A', title: '窗口一的会话', profile_id: null, created_at: '', updated_at: '', archived: false, last_turn_id: null }
    const sessionB = { id: 's_B', title: '新会话', profile_id: null, created_at: '', updated_at: '', archived: false, last_turn_id: null }
    let created = 0
    let streamCalls = 0

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const body = init?.body ? JSON.parse(String(init.body)) : undefined
        if (url.endsWith('/api/chat/stream')) {
          calls.push({ url, body })
          streamCalls += 1
          if (streamCalls === 1) {
            return jsonRes(
              {
                error: {
                  code: 'SessionBusy',
                  message: '该会话正在被另一个窗口生成',
                  detail: { running_client_id: 'win-1', client_id: 'win-2', same_client: false },
                  hint: '已自动开新会话',
                },
              },
              409,
            )
          }
          return sseRes(
            [
              ev('text_delta', 't_B', { text: '好的，这边是新会话' }, 0),
              ev('done', 't_B', { text: '好的，这边是新会话' }, 1),
            ],
            't_B',
          )
        }
        if (url.endsWith('/api/chat/sessions') && init?.method === 'POST') {
          created += 1
          return jsonRes({ session: sessionB }, 200)
        }
        if (url.includes('/messages')) {
          return jsonRes({ items: [], questions: [], count: 0, total: 0, has_more: false, session_id: 's_A' })
        }
        if (url.endsWith('/api/chat/sessions')) {
          return jsonRes({ sessions: [sessionA], groups: [{ key: 'today', label: '今天', items: [sessionA] }], count: 1 })
        }
        return jsonRes({}, 200)
      }),
    )

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>,
    )

    const ta = await screen.findByPlaceholderText(/说清楚你要什么/)
    fireEvent.change(ta, { target: { value: '帮我写一篇小红书' } })
    fireEvent.keyDown(ta, { key: 'Enter' })

    await waitFor(() => expect(streamCalls).toBe(2), { timeout: 3000 })
    expect(created).toBe(1)
    // 第一次撞在 A 会话上，第二次换到新会话
    expect((calls[0].body as { session_id: string }).session_id).toBe('s_A')
    expect((calls[1].body as { session_id: string }).session_id).toBe('s_B')
    expect((calls[1].body as { text: string }).text).toBe('帮我写一篇小红书')
    await waitFor(() => expect(screen.getByText('好的，这边是新会话')).toBeInTheDocument())
  })
})
