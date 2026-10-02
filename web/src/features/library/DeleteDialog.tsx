/** SPEC-05 §3.2 / UI-SPEC 规则 19 · DeleteDialog：破坏性操作二次确认。
 *
 * 两道锁：
 * 1. **后端口令**：`POST /library/confirm-token` 拿一次性 token，DELETE 必须带 `?confirm=`
 * 2. **逐字输入**：必须输入文件名（删项目则输入项目名）才解锁确认按钮
 *
 * 文案由后端 `warning` 字段下发（含「及其全部内容」），前后端说的是同一句话。
 */

import { useEffect, useState } from 'react'
import { ConfirmDialog, Chip, Skeleton, toast } from '@/components'
import { libraryApi } from './api'
import type { ConfirmToken, DeleteResult, LibFile } from './types'

export type DeleteTarget = { type: 'file'; file: LibFile } | { type: 'project'; name: string }

export type DeleteDialogProps = {
  target: DeleteTarget | null
  onClose: () => void
  onDeleted: (result: DeleteResult) => void
}

export function DeleteDialog({ target, onClose, onDeleted }: DeleteDialogProps) {
  const [token, setToken] = useState<ConfirmToken | null>(null)
  const [busy, setBusy] = useState(false)

  const key = target ? (target.type === 'file' ? `file:${target.file.path}` : `project:${target.name}`) : ''

  // 依赖 key 而不是 target 对象：换目标才重新取口令，同一个目标重开不重复申请
  useEffect(() => {
    setToken(null)
    if (!target) return
    let dead = false
    const body = target.type === 'file' ? { path: target.file.path } : { project: target.name }
    libraryApi
      .confirmToken(body)
      .then((t) => {
        if (!dead) setToken(t)
      })
      .catch((e: unknown) => {
        if (!dead) {
          toast.error(e instanceof Error ? e.message : '拿不到确认口令')
          onClose()
        }
      })
    return () => {
      dead = true
    }
  }, [key])

  if (!target) return null

  const typing = target.type === 'file' ? target.file.name : target.name
  const title = target.type === 'file' ? '删除这个文件' : '删除整个项目'

  const confirm = async () => {
    if (!token) return
    setBusy(true)
    try {
      const res =
        target.type === 'file'
          ? await libraryApi.deleteFile(target.file.path, token.token)
          : await libraryApi.deleteProject(target.name, token.token)
      toast.ok(res.statement)
      onDeleted(res)
      onClose()
    } catch (e) {
      // 403 SystemFileProtected / 422 口令失效，都由 api 层 toast 过，这里只收口
      toast.error(e instanceof Error ? e.message : '删除失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <ConfirmDialog
      open
      danger
      title={title}
      sub={token?.warning ?? '正在取确认口令…'}
      okText="确认删除"
      requireTyping={typing}
      onCancel={onClose}
      onConfirm={() => void confirm()}
    >
      {!token ? (
        <Skeleton width={280} height={56} />
      ) : (
        <div className="stack" style={{ gap: 9 }}>
          <p className="sysfile danger" style={{ marginBottom: 0 }}>
            {token.warning}
          </p>
          <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
            <Chip tone="outline" mono>
              {target.type === 'file' ? target.file.rel_to_root : `outputs/${target.name}`}
            </Chip>
            {token.size_human ? <Chip tone="outline">{token.size_human}</Chip> : null}
            {token.file_count != null ? (
              <>
                <Chip tone="outline">{token.file_count} 个文件</Chip>
                <Chip tone="outline">{token.total_size_human}</Chip>
              </>
            ) : null}
          </div>
          <p className="help">
            删除后不能撤销，也不会进回收站。想保留的话先「再想想」，或者到发布中心挂载一份再删。
          </p>
          {busy ? <p className="help">正在删除…</p> : null}
        </div>
      )}
    </ConfirmDialog>
  )
}

export default DeleteDialog
