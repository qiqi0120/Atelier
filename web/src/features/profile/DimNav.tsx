import type { LucideIcon } from 'lucide-react'
import { Lightbulb, Shield, SlidersHorizontal, Target, Users } from 'lucide-react'
import { Chip, ProgressBar } from '@/components'
import { DIM_KEYS, DIM_NAMES } from './api'
import type { DimKey } from './api'

/** 六维图标（与原型 #v-profile 左导航同款：target/pen/users/cog/shield/bulb） */
const ICONS: Record<DimKey, LucideIcon> = {
  identity: Target,
  style: SlidersHorizontal,
  audience: Users,
  platform_rules: SlidersHorizontal,
  preferences: Shield,
  memories: Lightbulb,
}

export type DimNavProps = {
  /** 六维完整度，后端 completeness() 算好的 0–100 */
  scores: Record<string, number>
  /** 六维均值 */
  overall: number
  value: DimKey
  onChange: (dim: DimKey) => void
}

/**
 * 左导航：六维 + 完整度进度条（UI-SPEC 规则 23 / 原型 dimNav）。
 * 数值直接用后端给的 completeness，不在前端二次算——口径只有一处。
 */
export function DimNav({ scores, overall, value, onChange }: DimNavProps) {
  return (
    <div className="card">
      <div className="card-h">
        <h3>六维</h3>
        <div className="sp">
          <Chip tone="accent">完整度 {overall}%</Chip>
        </div>
      </div>
      <div className="card-b tight dim-nav">
        {DIM_KEYS.map((k) => {
          const Icon = ICONS[k]
          const pct = scores[k] ?? 0
          return (
            <button
              key={k}
              type="button"
              className={k === value ? 'on' : ''}
              aria-current={k === value}
              onClick={() => onChange(k)}
            >
              <Icon size={15} strokeWidth={1.9} />
              <span>{DIM_NAMES[k]}</span>
              <span className="n">{pct}%</span>
              <div className="filled" style={{ width: '100%' }}>
                <i style={{ width: `${pct}%` }} />
              </div>
            </button>
          )
        })}
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--line-soft)' }}>
          <ProgressBar value={overall} label="画像完整度" />
          <div className="help" style={{ marginTop: 5 }}>
            完整度只是提醒，产出质量取决于内容本身有多具体。
          </div>
        </div>
      </div>
    </div>
  )
}

export default DimNav
