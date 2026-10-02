import { useEffect, useState } from 'react'
import { Activity } from 'lucide-react'

export type HeartbeatHintProps = {
  /** 生成中才有意义 */
  active: boolean
  /** 最近一次收到事件的时刻（ms） */
  lastEventAt: number
  /** 静默多少秒后提示（PRD F-B11：30s） */
  silentSeconds?: number
}

/**
 * 心跳提示（PRD F-B11）：生成中静默 30s 才出现「未卡住，继续生成中」。
 * 不做倒计时跳动——它只是「还在跑，别以为卡死了」的一句话。
 */
export function HeartbeatHint({ active, lastEventAt, silentSeconds = 30 }: HeartbeatHintProps) {
  const [silent, setSilent] = useState(false)

  useEffect(() => {
    if (!active) {
      setSilent(false)
      return
    }
    const tick = () => setSilent(lastEventAt > 0 && Date.now() - lastEventAt >= silentSeconds * 1000)
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [active, lastEventAt, silentSeconds])

  if (!active || !silent) return null
  return (
    <span className="typing" role="status">
      <Activity size={12} />
      未卡住，继续生成中（已静默 {silentSeconds}s）
    </span>
  )
}

export default HeartbeatHint
