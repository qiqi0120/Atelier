import { Check } from 'lucide-react'
import { Card, Chip } from '@/components'
import type { PlatformKey, PlatformMeta } from './types'

export type PlatformPickerProps = {
  platforms: PlatformMeta[]
  selected: PlatformKey[]
  /** 已适配完成的平台数（`.plat` 卡片头部「已生成 2/3」） */
  generated: number
  adapting: boolean
  onToggle: (p: PlatformKey) => void
  children?: React.ReactNode
  /** 头部操作区追加项（F-G19「优化建议」入口挂在适配结果/变体区域） */
  extraActions?: React.ReactNode
}

/**
 * 平台勾选 + 约束说明 + 登录态 chip（UI-SPEC 规则 16/18）。
 *
 * 登录态是**真校验**结果（后端读 platform_creds），不是固定文案：
 * 未登录显示灰 chip 并提示去扫码，已登录显示绿 chip。
 */
export function PlatformPicker({
  platforms,
  selected,
  generated,
  adapting,
  onToggle,
  children,
  extraActions,
}: PlatformPickerProps) {
  return (
    <Card
      title="平台适配"
      actions={
        <>
          <Chip tone="outline" className="adapt-state">
            {adapting ? `适配中 · ${generated}/${platforms.length}` : `已生成 ${generated} / ${platforms.length}`}
          </Chip>
          {extraActions}
        </>
      }
    >
      <div className="stack" style={{ gap: 8 }}>
        {platforms.map((p) => {
          const on = selected.includes(p.platform)
          return (
            <div key={p.platform}>
              <button
                type="button"
                className={`plat ${on ? 'on' : ''}`}
                aria-pressed={on}
                aria-label={`${p.name}${on ? '（已选择）' : '（未选择）'}`}
                onClick={() => onToggle(p.platform)}
              >
                <span className="ck" aria-hidden>
                  {on ? <Check size={10} /> : null}
                </span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span className="nm">{p.name}</span>
                  <span className="sub">{p.constraint}</span>
                </span>
                <AuthChip auth={p.auth} />
              </button>
              {children}
            </div>
          )
        })}
      </div>
    </Card>
  )
}

/** 登录态 chip：真实校验结果 → 三态上色。 */
export function AuthChip({ auth, xs }: { auth: PlatformMeta['auth']; xs?: boolean }) {
  if (!auth.logged_in) {
    return (
      <Chip tone="outline" xs={xs} title={auth.message}>
        未登录
      </Chip>
    )
  }
  return (
    <Chip tone={auth.need_sms ? 'warn' : 'accent'} xs={xs} title={auth.message}>
      {auth.need_sms ? '需短信' : '已登录'}
    </Chip>
  )
}

export default PlatformPicker
