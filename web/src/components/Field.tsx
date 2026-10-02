import { useId } from 'react'
import type { ReactNode } from 'react'

export type FieldProps = {
  label: string
  /** 说明文案（11.5px），可带强调片段 */
  help?: ReactNode
  error?: ReactNode
  required?: boolean
  children: (id: string) => ReactNode
  className?: string
}

/** 表单字段容器：label + 控件 + help/error（UI-SPEC §4） */
export function Field({ label, help, error, required, children, className = '' }: FieldProps) {
  const id = useId()
  return (
    <div className={['field', className].filter(Boolean).join(' ')}>
      <label htmlFor={id}>
        {label}
        {required ? <span style={{ color: 'var(--danger-ink)' }}> *</span> : null}
      </label>
      {children(id)}
      {error ? <span className="err">{error}</span> : help ? <span className="help">{help}</span> : null}
    </div>
  )
}

export default Field
