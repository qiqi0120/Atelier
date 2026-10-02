import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Construction } from 'lucide-react'
import { Button, Chip, EmptyState } from '@/components'
import { PageHead } from './PageHead'

export type M2PlaceholderProps = {
  title: string
  desc: string
  /** 该域在 M2 的主行动（UI-SPEC §6） */
  primaryLabel: string
  /** 占位说明：这个域接上后能做什么 */
  willDo: string
  /** 未接入的具体原因，写清楚，不只写「未实现」 */
  blockedBy: string
  /** 建议用户先做什么 */
  fallbackTo?: { to: string; label: string }
  extra?: ReactNode
}

/** M2 域占位页：页头 + EmptyState（含「M2 接入」说明）+ 一个下一步按钮（SPEC-07 §2） */
export function M2Placeholder({
  title,
  desc,
  primaryLabel,
  willDo,
  blockedBy,
  fallbackTo = { to: '/chat', label: '先去对话工作台' },
  extra,
}: M2PlaceholderProps) {
  const navigate = useNavigate()
  return (
    <div className="view-pad">
      <PageHead title={title} desc={desc} />
      <div className="card">
        <div className="card-b">
          <EmptyState
            icon={
              <div className="qi" style={{ margin: '0 auto 12px', width: 40, height: 40, borderRadius: 12 }}>
                <Construction size={20} />
              </div>
            }
            title={
              <>
                <Chip tone="warn" style={{ marginRight: 6 }}>
                  M2 接入
                </Chip>
                这个域还没接后端
              </>
            }
            description={
              <>
                {willDo}
                <br />
                <br />
                <b style={{ color: 'var(--ink-2)' }}>阻塞原因：</b>
                {blockedBy}
              </>
            }
            action={
              <div className="row" style={{ gap: 8, flexWrap: 'wrap', justifyContent: 'center' }}>
                <Button variant="primary" disabled disabledReason={blockedBy} onClick={() => navigate(fallbackTo.to)}>
                  {primaryLabel}
                </Button>
                <Button variant="default" onClick={() => navigate(fallbackTo.to)}>
                  {fallbackTo.label}
                </Button>
              </div>
            }
          />
          {extra}
        </div>
      </div>
    </div>
  )
}

export default M2Placeholder
