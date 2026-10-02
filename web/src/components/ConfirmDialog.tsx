import { useState } from 'react'
import type { ReactNode } from 'react'
import { AlertTriangle, Lock } from 'lucide-react'
import { Modal } from './Modal'
import { Button } from './Button'

export type ConfirmDialogProps = {
  open: boolean
  title: ReactNode
  sub?: ReactNode
  /** 弹窗正文，通常是后果说明 + 二次确认输入框的上下文 */
  children?: ReactNode
  okText?: string
  cancelText?: string
  danger?: boolean
  /**
   * 破坏性操作：要求用户逐字输入该字符串（如文件名）才允许确认。
   * PRD F-G7 —— 删文件 / 登出必须二次确认。
   */
  requireTyping?: string
  onCancel: () => void
  onConfirm: () => void
}

/** 破坏性操作二次确认弹窗（SPEC-07 §1.6：破坏性接口不允许在按钮上直接调） */
export function ConfirmDialog({
  open,
  title,
  sub,
  children,
  okText = '确认',
  cancelText = '再想想',
  danger = false,
  requireTyping,
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  const [typed, setTyped] = useState('')
  const locked = Boolean(requireTyping) && typed.trim() !== requireTyping

  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      sub={sub}
      icon={
        <div
          className="qi"
          style={{
            width: 32,
            height: 32,
            borderRadius: 10,
            background: danger ? 'var(--danger-soft)' : 'var(--warn-soft)',
            color: danger ? 'var(--danger-ink)' : 'var(--warn-ink)',
          }}
        >
          {danger ? <Lock size={17} /> : <AlertTriangle size={17} />}
        </div>
      }
      closeOnScrim={false}
      footer={
        <>
          <Button onClick={onCancel}>{cancelText}</Button>
          <Button
            variant={danger ? 'danger' : 'primary'}
            disabled={locked}
            disabledReason={requireTyping ? `请输入 ${requireTyping} 以确认` : undefined}
            onClick={() => {
              if (locked) return
              setTyped('')
              onConfirm()
            }}
          >
            {okText}
          </Button>
        </>
      }
    >
      {children}
      {requireTyping ? (
        <div className="field" style={{ marginTop: 10 }}>
          <label htmlFor="confirm-typing">二次确认（只影响破坏性操作）</label>
          <input
            id="confirm-typing"
            className="inp mono"
            placeholder={`输入 ${requireTyping} 以确认`}
            value={typed}
            autoComplete="off"
            onChange={(e) => setTyped(e.target.value)}
          />
        </div>
      ) : null}
    </Modal>
  )
}

export default ConfirmDialog
