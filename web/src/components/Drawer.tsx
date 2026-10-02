import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

export type DrawerProps = {
  open: boolean
  onClose: () => void
  title?: ReactNode
  /** 标题下方的元信息行（id / 层 / 成本） */
  meta?: ReactNode
  children?: ReactNode
  footer?: ReactNode
  width?: number
}

/** 右侧 560px，transform 260ms 弹出，带遮罩（UI-SPEC §4） */
export function Drawer({ open, onClose, title, meta, children, footer, width }: DrawerProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (typeof document === 'undefined' || !open) return null

  return createPortal(
    <>
      <div className="scrim on" onClick={onClose} data-testid="scrim" />
      <aside
        className="drawer on"
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : '详情'}
        style={width ? { width: `min(${width}px, 94vw)` } : undefined}
      >
        <div className="drawer-h">
          <div style={{ flex: 1, minWidth: 0 }}>
            {title != null ? <h2>{title}</h2> : null}
            {meta != null ? <div className="row" style={{ gap: 7, marginTop: 6, flexWrap: 'wrap' }}>{meta}</div> : null}
          </div>
          <button type="button" className="iconbtn" aria-label="关闭" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        <div className="drawer-b">{children}</div>
        {footer != null ? <div className="drawer-f">{footer}</div> : null}
      </aside>
    </>,
    document.body,
  )
}

export default Drawer
