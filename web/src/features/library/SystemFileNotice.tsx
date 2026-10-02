/** SPEC-05 §4 · SystemFileNotice：顶部琥珀提示条（原型 `.sysfile`）。
 *
 * `.session/` 与 `.index.json` 受系统保护、禁止删除（UI-SPEC 规则 20）。
 * 这里同时是解锁入口——但后端 M1 只回提示，不真的解锁，所以按钮点完会说明这一点，
 * 不给「已解锁」的错觉。
 */

import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { toast } from '@/components'
import { libraryApi } from './api'

export type SystemFileNoticeProps = {
  /** 当前浏览的目录里有没有系统文件；有才显示，避免常驻噪音 */
  visible: boolean
  /** 触发解锁询问的目标（一般是当前 .session 目录） */
  targetPath?: string
}

export function SystemFileNotice({ visible, targetPath }: SystemFileNoticeProps) {
  const [busy, setBusy] = useState(false)
  if (!visible) return null

  const ask = async () => {
    if (!targetPath) {
      toast.warn('先在左侧点开 .session 目录，再点解锁')
      return
    }
    setBusy(true)
    try {
      const res = await libraryApi.unlockSystem(targetPath, '解锁系统文件')
      toast.warn(`${res.message}。${res.notice}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '解锁失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="sysfile" data-testid="system-notice">
      <AlertTriangle size={13} />
      <span>会话日志（.session/）、索引文件（.index.json）受系统保护，删除需先在设置里解锁。</span>
      <button
        type="button"
        className="btn sm ghost"
        style={{ marginLeft: 'auto' }}
        onClick={() => void ask()}
        disabled={busy}
      >
        <span className="btn-txt">{busy ? '查询中…' : '解锁系统文件'}</span>
      </button>
    </div>
  )
}

export default SystemFileNotice
