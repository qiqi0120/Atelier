import { AlertTriangle, Check, X } from 'lucide-react'
import { Button, Card, Chip, EmptyState } from '@/components'
import type { PlatformRun, PublishRecord } from './types'

export type PublishStatusListProps = {
  /** 本次发布刚返回的结果（最新在前） */
  runs: PlatformRun[]
  /** 历史记录（上次发布） */
  records: PublishRecord[]
  pendingPlatforms: string[]
  onGoAccounts: () => void
  onRetry: (recordId: string) => void
}

/**
 * 发布状态跟踪（F-G18 / UI-SPEC 规则 21）。
 *
 * ★ 失败必须显示**原因 + 错误码 + 处理按钮**（原则四：不许只显示「失败」）。
 * ★ dry-run 的结果明确标注「模拟」，不让用户误以为真发出去了。
 */
export function PublishStatusList({
  runs,
  records,
  pendingPlatforms,
  onGoAccounts,
  onRetry,
}: PublishStatusListProps) {
  const hasAny = runs.length > 0 || records.length > 0 || pendingPlatforms.length > 0

  return (
    <Card
      title="发布状态"
      actions={<Chip tone="outline">{records.length > 0 ? `上次 ${hhmm(records[0]?.created_at)}` : '暂无记录'}</Chip>}
    >
      {!hasAny ? (
        <EmptyState
          title="还没有发布记录"
          description="发布后这里会逐平台显示状态：发布中、已发、失败原因与错误码。失败的单条可以重试。"
        />
      ) : (
        <>
          {pendingPlatforms.length > 0 ? (
            <div className="status-row">
              <div className="st wait" aria-hidden>
                —
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <b className="mut">本次发布</b>
                <div className="mut2" style={{ fontSize: 11.5 }}>
                  等待确认 · {pendingPlatforms.length} 个平台
                </div>
              </div>
              <Chip tone="outline">待发</Chip>
            </div>
          ) : null}

          {runs.map((r) => (
            <Row key={`run-${r.platform}`} run={r} onGoAccounts={onGoAccounts} />
          ))}

          {records.map((r) => (
            <div className="status-row" key={r.id} data-testid={`record-${r.platform}`}>
              <div className={`st ${r.status === 'sent' ? 'ok' : r.status === 'failed' ? 'err' : 'wait'}`} aria-hidden>
                {r.status === 'sent' ? <Check size={11} /> : r.status === 'failed' ? <X size={11} /> : '—'}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <b>{r.title || r.platform_name}</b>
                <div className="mut2" style={{ fontSize: 11.5 }}>
                  {r.platform_name} · {statusText(r.status)}
                  {r.status === 'failed' && r.error ? `：${r.error}` : ''}
                  {r.status === 'failed' && r.error_code ? `（错误码 ${r.error_code}）` : ''}
                  {r.hint && r.status === 'failed' ? ` — ${r.hint}` : ''}
                </div>
              </div>
              {r.status === 'failed' && r.error_code?.includes('auth') ? (
                <Button size="sm" onClick={onGoAccounts}>
                  去登录
                </Button>
              ) : r.status === 'failed' ? (
                <Button size="sm" onClick={() => onRetry(r.id)}>
                  重试
                </Button>
              ) : (
                <Chip tone="outline" mono>
                  {relTime(r.created_at)}
                </Chip>
              )}
            </div>
          ))}
        </>
      )}
    </Card>
  )
}

function Row({ run, onGoAccounts }: { run: PlatformRun; onGoAccounts: () => void }) {
  const ok = run.status === 'sent'
  const failed = run.status === 'failed' || run.status === 'awaiting_sms'
  return (
    <div className="status-row" data-testid={`run-${run.platform}`} data-status={run.status}>
      <div className={`st ${ok ? 'ok' : failed ? 'err' : 'run'}`} aria-hidden>
        {ok ? <Check size={11} /> : failed ? <X size={11} /> : <AlertTriangle size={11} />}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <b>{run.name}</b>
        <div className="mut2" style={{ fontSize: 11.5 }}>
          {run.status === 'sent'
            ? `${run.name} · 已发`
            : run.status === 'awaiting_sms'
              ? `${run.name} · 等待短信验证码`
              : `${run.name} · 发布失败`}
          {run.error ? `：${run.error}` : ''}
          {run.error_code ? `（错误码 ${run.error_code}）` : ''}
          {run.hint && failed ? ` — ${run.hint}` : ''}
        </div>
      </div>
      {run.error_code?.includes('auth') ? (
        <Button size="sm" onClick={onGoAccounts} data-testid={`go-login-${run.platform}`}>
          去登录
        </Button>
      ) : ok && run.dry_run ? (
        <Chip tone="warn" xs title="本批为模拟执行（dry-run），校验真实执行但没有真实发出">
          模拟
        </Chip>
      ) : ok ? (
        <Chip tone="accent" xs>
          已发
        </Chip>
      ) : failed ? (
        <Chip tone="danger" xs>
          失败
        </Chip>
      ) : null}
    </div>
  )
}

function statusText(s: string): string {
  return { sent: '已发', failed: '发布失败', publishing: '发布中', awaiting_sms: '等待短信' }[s] ?? s
}

function hhmm(iso: string | null | undefined): string {
  if (!iso) return '--:--'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '--:--' : `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

function relTime(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (Number.isNaN(diff)) return ''
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}m 前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h 前`
  return `${Math.floor(diff / 86400)}d 前`
}

export default PublishStatusList
