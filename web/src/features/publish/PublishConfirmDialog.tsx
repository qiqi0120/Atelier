import { Modal } from '@/components'
import type { PlatformMeta } from './types'

export type PublishConfirmDialogProps = {
  open: boolean
  platforms: PlatformMeta[]
  onCancel: () => void
  onConfirm: () => void
  busy?: boolean
}

/**
 * 发布二次确认（UI-SPEC 规则 18 / SPEC-06 §4）。
 *
 * ★ 必须列出**每个平台的形态与登录态**——用户点确认前要能看到「发出去是什么样」。
 * ★ 明确标出本批为模拟执行（dry-run），不许让用户误以为真发出去了。
 */
export function PublishConfirmDialog({ open, platforms, onCancel, onConfirm, busy }: PublishConfirmDialogProps) {
  const notLoggedIn = platforms.filter((p) => !p.auth.logged_in)
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title="确认发布"
      sub={`将发布到 ${platforms.length} 个平台`}
      closeOnScrim={false}
      onOk={onConfirm}
      okText={busy ? '发布中…' : `确认发布到 ${platforms.length} 个平台`}
    >
      <div className="stack" style={{ gap: 10 }}>
        <div className="stack" style={{ gap: 6 }} data-testid="confirm-platforms">
          {platforms.map((p) => (
            <div className="status-row" key={p.platform} style={{ padding: '8px 0' }}>
              <div className={`st ${p.auth.logged_in ? 'ok' : 'err'}`} aria-hidden>
                {p.auth.logged_in ? '✓' : '✗'}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <b>{p.name}</b>
                <div className="mut2" style={{ fontSize: 11.5 }}>
                  形态：{p.form_label} · 标题 ≤ {p.title_max} 字 · 正文 ≤ {p.body_max} 字
                  {p.needs_cover ? ` · 需封面图（${p.cover_ratio}）` : ''}
                </div>
              </div>
              <span className={`chip ${p.auth.logged_in ? (p.auth.need_sms ? 'w' : 'a') : 'o'}`}>
                {p.auth.logged_in ? (p.auth.need_sms ? '已登录 · 可能要短信' : '已登录') : '未登录'}
              </span>
            </div>
          ))}
        </div>
        {notLoggedIn.length > 0 ? (
          <p className="help" style={{ color: 'var(--danger-ink)' }}>
            {notLoggedIn.map((p) => p.name).join('、')} 还没登录，现在发布会失败。先去「账号登录」扫码再回来。
          </p>
        ) : null}
        <p className="help">
          <b>模拟执行说明</b>：本批发布通道为 dry-run —— 字数 / 封面 / 形态 / 登录态校验都是真的，
          但<b>不会向平台真实发出内容</b>。真实发布需要真实账号与平台风控验证，属 M4 批次。
        </p>
      </div>
    </Modal>
  )
}

export default PublishConfirmDialog
