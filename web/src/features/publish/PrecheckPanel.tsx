import { AlertTriangle, Check, X } from 'lucide-react'
import { Button, Card, Chip, EmptyState } from '@/components'
import { checkTone } from './types'
import type { PrecheckItem, PrecheckResult } from './types'

export type PrecheckPanelProps = {
  result: PrecheckResult | null
  loading: boolean
  /** 硬门禁的修复动作（点「一键裁剪」→ 调 autofix） */
  onAutofix: (platform: string, field: 'body' | 'title' | 'all') => void
  onGoAccounts: () => void
  onGoLibrary: () => void
  onRerun: () => void
}

/**
 * 发布前预检（UI-SPEC 规则 17 / SPEC-06 §3）。
 *
 * 上色规则：**通过绿 ✓ / 软提醒琥珀 ! / 硬门禁红 ✗**。
 * ★ 人设一致性永远是琥珀色软提醒——它**不会**阻断发布（F-G13 硬要求）。
 */
export function PrecheckPanel({
  result,
  loading,
  onAutofix,
  onGoAccounts,
  onGoLibrary,
  onRerun,
}: PrecheckPanelProps) {
  if (!result) {
    return (
      <Card title="发布前预检">
        <EmptyState
          title="还没有跑预检"
          description="预检会逐项检查合规风险、字数门禁、封面图、登录态、出站密钥，以及标题打分与人设一致性（软提醒）。"
          action={
            <Button variant="primary" loading={loading} onClick={onRerun}>
              跑一次预检
            </Button>
          }
        />
      </Card>
    )
  }

  const items = Array.isArray(result.items) ? result.items : []
  const blocks = typeof result.block_count === 'number' ? result.block_count : 0
  const warns = typeof result.warn_count === 'number' ? result.warn_count : 0
  const blocked = Boolean(result.blocked)

  return (
    <Card
      title="发布前预检"
      actions={
        blocked || blocks > 0 ? (
          <Chip tone="danger" className="precheck-blocks">
            {blocks} 项待处理
          </Chip>
        ) : warns > 0 ? (
          <Chip tone="warn" className="precheck-warns">
            {warns} 项软提醒
          </Chip>
        ) : (
          <Chip tone="accent">全部通过</Chip>
        )
      }
    >
      <div data-testid="precheck-items">
        {items.length === 0 ? (
          <p className="help">后端没有返回任何预检项——这不算「全部通过」，请重跑一次。</p>
        ) : null}
        {items.map((item) => (
          <Row key={item.id} item={item} onAutofix={onAutofix} onGoAccounts={onGoAccounts} onGoLibrary={onGoLibrary} />
        ))}
      </div>
      <p className="help" style={{ marginTop: 9 }}>
        红 ✗ 是硬门禁，必须修才能发；琥珀 ! 只是提醒——比如人设一致性，<b>不会</b>拦你发布。
      </p>
    </Card>
  )
}

function Row({
  item,
  onAutofix,
  onGoAccounts,
  onGoLibrary,
}: {
  item: PrecheckItem
  onAutofix: (platform: string, field: 'body' | 'title' | 'all') => void
  onGoAccounts: () => void
  onGoLibrary: () => void
}) {
  const tone = checkTone(item)
  const platform = item.platform ?? ''
  // 抖音标题与正文同限 55：两个都超时必须**两个都裁**，只裁一个门禁解不掉。
  // 判断依据是 message（后端把「标题 61/55，正文 66/55」都写在 message 里，
  // label 只有一个「抖音标题超字数」）。
  const mentions = `${item.label} ${item.message}`
  const field: 'body' | 'title' | 'all' =
    mentions.includes('标题') && mentions.includes('正文')
      ? 'all'
      : mentions.includes('标题')
        ? 'title'
        : 'body'

  return (
    <div className="precheck" data-testid={`precheck-${item.id}`} data-tone={tone}>
      <div className={`s ${tone}`} aria-hidden>
        {tone === 'ok' ? <Check size={10} /> : tone === 'w' ? <AlertTriangle size={10} /> : <X size={10} />}
      </div>
      <div style={{ minWidth: 0 }}>
        <b>{item.label}</b>
        <span>{item.message}</span>
        {item.fix_hint && tone !== 'ok' ? <span className="mut2">→ {item.fix_hint}</span> : null}
        {tone === 'd' ? (
          <div className="row" style={{ gap: 7, marginTop: 7, flexWrap: 'wrap' }}>
            {item.id.startsWith('wordcount:') ? (
              <Button size="sm" data-testid={`autofix-${platform}`} onClick={() => onAutofix(platform, field)}>
                一键裁剪
              </Button>
            ) : null}
            {item.id.startsWith('auth:') ? (
              <Button size="sm" onClick={onGoAccounts}>
                去登录
              </Button>
            ) : null}
            {item.id.startsWith('cover:') ? (
              <Button size="sm" onClick={onGoLibrary}>
                去内容库挂封面
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}

export default PrecheckPanel
