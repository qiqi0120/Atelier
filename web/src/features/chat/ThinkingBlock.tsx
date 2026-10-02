import { Brain } from 'lucide-react'

export type ThinkingBlockProps = {
  text: string
  /** 思考耗时（ms）；没结束还没有值 */
  ms: number | null
  done: boolean
  defaultOpen?: boolean
}

function fmtMs(ms: number | null): string {
  if (ms == null) return '进行中'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

/**
 * 思考过程独立可折叠（UI-SPEC 规则 6 / F-B1）。
 * 用原生 `<details>`，展开状态交给浏览器，刷新后不丢。
 */
export function ThinkingBlock({ text, ms, done, defaultOpen = false }: ThinkingBlockProps) {
  if (!text) return null
  return (
    <details className="think" open={defaultOpen}>
      <summary>
        <Brain size={12} />
        思考过程（{fmtMs(ms)}）
        {done ? null : <i className="live-dot" style={{ marginLeft: 2 }} />}
      </summary>
      <div className="tb">{text}</div>
    </details>
  )
}

export default ThinkingBlock
