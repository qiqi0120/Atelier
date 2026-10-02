import { Chip } from '@/components'
import type { PlatformVariant } from './types'

export type PlatformVariantCardProps = {
  variant: PlatformVariant
  /** 适配中的逐字文本（F-G10 打字机）。未适配为 undefined。 */
  streaming?: string
  /** 该平台是否被勾选 */
  selected?: boolean
}

/**
 * 单平台适配结果卡（原型 `.pv`）：
 * 逐平台字数 `618 / 1000` + 进度条 + **超限标红** + 渐隐遮罩预览 + 适配中打字机。
 *
 * ★ **字数读数全部来自后端**（``variant.char_count`` / ``char_limit``），
 * 前端**不做任何计数实现**（SPEC-06 §2）。
 */
export function PlatformVariantCard({ variant, streaming, selected = true }: PlatformVariantCardProps) {
  const adapting = variant.status === 'adapting'
  const text = adapting ? (streaming ?? '') : variant.body
  const over = variant.over_limit
  const pct = variant.char_limit > 0 ? (variant.char_count / variant.char_limit) * 100 : 0
  const what = variant.platform === 'dy' ? '标题 / 描述' : '标题 / 正文'

  if (!selected) return null

  return (
    <div className="pv" data-testid={`pv-${variant.platform}`} data-over={over ? 'true' : 'false'}>
      <div className="hd">
        <span>{what}</span>
        <span
          className={`cnt ${over ? 'over' : ''}`}
          data-testid={`cnt-${variant.platform}`}
          aria-label={over ? `${variant.char_count} 字，超出上限 ${variant.char_limit} 字` : undefined}
        >
          {variant.char_count} / {variant.char_limit}
        </span>
      </div>
      {/* 进度条：超限时 `.limit i.over` 转红（原型同款；.bd::after 是渐隐遮罩） */}
      <div
        className="limit"
        role="progressbar"
        aria-valuenow={variant.char_count}
        aria-valuemin={0}
        aria-valuemax={variant.char_limit}
        aria-label={`${variant.platform} 字数占用`}
      >
        <i className={over ? 'over' : undefined} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
      </div>
      <div className="bd" data-testid={`pv-body-${variant.platform}`}>
        {adapting ? (
          <span>
            {text}
            <span className="caret" aria-label="适配中" />
          </span>
        ) : variant.error ? (
          <span style={{ color: 'var(--danger-ink)' }}>{variant.error}</span>
        ) : text ? (
          text
        ) : (
          <span className="mut">还没适配</span>
        )}
      </div>
      {over && !adapting ? (
        <div style={{ marginTop: 7 }}>
          <Chip tone="danger" xs>
            超出上限 {variant.char_count - variant.char_limit} 字，属硬门禁
          </Chip>
        </div>
      ) : null}
    </div>
  )
}

export default PlatformVariantCard
