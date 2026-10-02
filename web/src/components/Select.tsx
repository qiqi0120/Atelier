import { useId } from 'react'
import type { SelectHTMLAttributes } from 'react'

export type SelectOption = { value: string; label: string; disabled?: boolean }

export type SelectProps = {
  label?: string
  help?: string
  error?: string
  options: SelectOption[]
  /** 未选中时的占位项 */
  placeholder?: string
  sizeSm?: boolean
} & Omit<SelectHTMLAttributes<HTMLSelectElement>, 'children'>

/** 下拉选择，外观与 .inp 一致（原生 select + CSS 箭头） */
export function Select({ label, help, error, options, placeholder, sizeSm, className = '', id, ...rest }: SelectProps) {
  const auto = useId()
  const selectId = id ?? auto
  return (
    <div className="field">
      {label ? <label htmlFor={selectId}>{label}</label> : null}
      <div className="sel">
        <select
          id={selectId}
          className={['inp', sizeSm ? 'sm' : '', className].filter(Boolean).join(' ')}
          aria-invalid={error ? true : undefined}
          {...rest}
        >
          {placeholder ? <option value="">{placeholder}</option> : null}
          {options.map((o) => (
            <option key={o.value} value={o.value} disabled={o.disabled}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      {error ? <span className="err">{error}</span> : help ? <span className="help">{help}</span> : null}
    </div>
  )
}

export default Select
