import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, Check, Info } from 'lucide-react'

export type ToastKind = 'info' | 'ok' | 'warn' | 'error'

export type ToastItem = {
  id: number
  message: string
  kind: ToastKind
}

let seq = 0
let items: ToastItem[] = []
const subs = new Set<(t: ToastItem[]) => void>()

function emit() {
  subs.forEach((fn) => fn([...items]))
}

/** 全局 toast 入口：右下角堆叠，2800ms 自动消失（UI-SPEC §4） */
export function pushToast(message: string, kind: ToastKind = 'info', ttl = 2800) {
  const id = ++seq
  items = [...items, { id, message, kind }].slice(-4)
  emit()
  if (ttl > 0) {
    setTimeout(() => {
      items = items.filter((t) => t.id !== id)
      emit()
    }, ttl)
  }
  return id
}

/** 既可 toast('文案') 直接调用，也可 toast.ok / toast.warn / toast.error */
export const toast = Object.assign(
  (message: string, kind: ToastKind = 'info', ttl = 2800) => pushToast(message, kind, ttl),
  {
    info: (m: string) => pushToast(m, 'info'),
    ok: (m: string) => pushToast(m, 'ok'),
    warn: (m: string) => pushToast(m, 'warn'),
    error: (m: string) => pushToast(m, 'error'),
  },
)

function Icon({ kind }: { kind: ToastKind }) {
  if (kind === 'ok') return <Check size={13} aria-hidden />
  if (kind === 'warn' || kind === 'error') return <AlertTriangle size={13} aria-hidden />
  return <Info size={13} aria-hidden />
}

/** Toast 宿主组件，挂在 App 根部 */
export function ToastHost() {
  const [list, setList] = useState<ToastItem[]>([])
  useEffect(() => {
    subs.add(setList)
    setList([...items])
    return () => {
      subs.delete(setList)
    }
  }, [])

  if (typeof document === 'undefined') return null

  return createPortal(
    <div className="toasts" role="status" aria-live="polite" data-testid="toasts">
      {list.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`} data-kind={t.kind}>
          <Icon kind={t.kind} />
          <span>{t.message}</span>
        </div>
      ))}
    </div>,
    document.body,
  )
}

export default ToastHost
