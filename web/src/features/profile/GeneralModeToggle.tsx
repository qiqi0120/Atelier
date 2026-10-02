import { useState } from 'react'
import { Button, Chip, toast } from '@/components'

export type GeneralModeToggleProps = {
  enabled: boolean
  profileName: string
  onToggle: (enabled: boolean) => Promise<void>
}

/**
 * 通用模式开关（spec 验收 1 / 验收 3）。
 * 切换时必须 toast 说明**影响范围**——这是唯一一个「关掉之后产出风格会变」的开关，
 * 不说清楚用户会以为画像丢了。
 */
export function GeneralModeToggle({ enabled, profileName, onToggle }: GeneralModeToggleProps) {
  const [busy, setBusy] = useState(false)

  const flip = async () => {
    if (busy) return
    setBusy(true)
    try {
      await onToggle(!enabled)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <div className="card-h">
        <h3>通用模式</h3>
        <div className="sp">
          <Chip tone="outline">无画像也能用</Chip>
        </div>
      </div>
      <div className="card-b">
        <div className="row" style={{ gap: 10 }}>
          <div style={{ flex: 1 }}>
            <div className="row" style={{ gap: 7 }}>
              <b style={{ fontSize: 13 }}>不带画像直接创作</b>
              <Chip tone={enabled ? 'warn' : 'accent'}>{enabled ? '已开启' : '已关闭'}</Chip>
            </div>
            <div className="help" style={{ marginTop: 3 }}>
              打开后本会话不注入画像，适合临时起稿；不会覆盖已有画像，「{profileName}」还在。
            </div>
          </div>
          <Button loading={busy} onClick={() => void flip()}>
            {enabled ? '关掉' : '开启'}
          </Button>
        </div>
        {enabled ? (
          <div className="help" style={{ marginTop: 8 }}>
            现在这一轮的系统提示里<strong>一个画像字都不会有</strong>——可在编辑器里用
            「预览 system_prompt」亲眼确认。
          </div>
        ) : null}
      </div>
    </div>
  )
}

/** 切换成功后的统一文案（调用方用它，避免各处各写一份） */
export function generalModeToast(enabled: boolean) {
  if (enabled) {
    toast.warn('已切到通用模式：这一轮开始不注入画像，随时可以切回来')
  } else {
    toast.ok('已切回画像模式：下一轮对话立即按画像产出')
  }
}

export default GeneralModeToggle
