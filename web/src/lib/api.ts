/* =============================================================================
   Atelier · 唯一 API client（SPEC-07 §1.8 / §4）
   - 非 2xx → 抛 ApiError（解析后端 {error:{code,message,detail,hint}}）
   - 204 → undefined
   - ApiError 自动 toast（除非调用方声明 handled: true）
   ========================================================================== */

export class ApiError extends Error {
  code: string
  http: number
  detail?: unknown
  hint?: string

  constructor(code: string, http: number, message: string, detail?: unknown, hint?: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.http = http
    this.detail = detail
    this.hint = hint
  }

  /** 展示给用户的一句话：人话 + 可执行的修复建议（原则四：失败要说清原因） */
  get display(): string {
    return this.hint ? `${this.message}（${this.hint}）` : this.message
  }
}

export type ToastSink = (message: string, kind: 'ok' | 'warn' | 'error' | 'info') => void

let sink: ToastSink | null = null

/** App 启动时注册 Toast 出口 */
export function setToastSink(fn: ToastSink | null) {
  sink = fn
}

export type RequestOptions = RequestInit & {
  /** 调用方自己处理错误时置 true，避免重复 toast */
  handled?: boolean
  /** 覆盖自动 toast 文案 */
  silent?: boolean
}

const BASE = '/api'

function buildUrl(path: string): string {
  if (/^https?:/i.test(path)) return path
  return `${BASE}${path.startsWith('/') ? path : `/${path}`}`
}

async function parseError(res: Response): Promise<ApiError> {
  let code = 'Unknown'
  let message = `请求失败（HTTP ${res.status}）`
  let detail: unknown
  let hint: string | undefined
  try {
    const body = (await res.json()) as { error?: { code?: string; message?: string; detail?: unknown; hint?: string } }
    if (body?.error) {
      code = body.error.code ?? code
      message = body.error.message ?? message
      detail = body.error.detail
      hint = body.error.hint
    }
  } catch {
    /* 非 JSON 响应，保留默认文案 */
  }
  return new ApiError(code, res.status, message, detail, hint)
}

export async function request<T>(path: string, init: RequestOptions = {}): Promise<T> {
  const { handled, silent, ...rest } = init
  let res: Response
  try {
    res = await fetch(buildUrl(path), {
      ...rest,
      headers: {
        ...(rest.body ? { 'Content-Type': 'application/json' } : {}),
        ...(rest.headers ?? {}),
      },
    })
  } catch (e) {
    const err = new ApiError('NetworkError', 0, '连不上本地服务', undefined, '确认后端已在 127.0.0.1:8000 运行')
    if (!handled && !silent) sink?.(err.display, 'error')
    throw err
  }

  if (!res.ok) {
    const err = await parseError(res)
    if (!handled && !silent) sink?.(err.display, res.status >= 500 ? 'error' : 'warn')
    throw err
  }

  if (res.status === 204) return undefined as T
  const text = await res.text()
  if (!text) return undefined as T
  try {
    return JSON.parse(text) as T
  } catch {
    return text as unknown as T
  }
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>(path, { ...opts, method: 'GET' }),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>(path, { ...opts, method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  del: <T>(path: string, opts?: RequestOptions) => request<T>(path, { ...opts, method: 'DELETE' }),
}
