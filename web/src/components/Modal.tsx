import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

export type ModalProps = {
  open: boolean
  onClose: () => void
  title?: ReactNode
  sub?: ReactNode
  icon?: ReactNode
  children?: ReactNode
  /** 底部操作区（默认「取消 / 确认」） */
  footer?: ReactNode
  onOk?: () => void
  okText?: string
  okVariant?: 'primary' | 'danger'
  /** 遮罩点击是否关闭（破坏性确认一般应为 false） */
  closeOnScrim?: boolean
  width?: number
}

/** 居中 520px，缩放+淡入 220ms（UI-SPEC §4） */
export function Modal({
  open,
  onClose,
  title,
  sub,
  icon,
  children,
  footer,
  onOk,
  okText = '确认',
  okVariant = 'primary',
  closeOnScrim = true,
  width,
}: ModalProps) {
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
      <div className="scrim on" onClick={closeOnScrim ? onClose : undefined} data-testid="scrim" />
      <div
        className="modal on"
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : undefined}
        style={width ? { width: `min(${width}px, 94vw)` } : undefined}
      >
        {title != null ? (
          <div className="card-h" style={{ border: 0, padding: '18px 20px 10px' }}>
            {icon}
            <div style={{ flex: 1, minWidth: 0 }}>
              <h3 style={{ fontSize: 15, fontWeight: 600 }}>{title}</h3>
              {sub ? (
                <p className="mut" style={{ fontSize: 'var(--fs-sub)', marginTop: 2 }}>
                  {sub}
                </p>
              ) : null}
            </div>
            <button type="button" className="iconbtn" aria-label="关闭" onClick={onClose}>
              <X size={16} />
            </button>
          </div>
        ) : null}
        {children != null ? <div style={{ padding: '0 20px 6px' }}>{children}</div> : null}
        {footer != null || onOk ? (
          <div className="drawer-f" style={{ justifyContent: 'flex-end' }}>
            {footer}
            {onOk ? (
              <button type="button" className={`btn ${okVariant === 'danger' ? 'danger' : 'pri'}`} onClick={onOk}>
                <span className="btn-txt">{okText}</span>
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </>,
    document.body,
  )
}

export default Modal
