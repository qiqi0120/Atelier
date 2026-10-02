/** =============================================================================
   账号登录中心（SPEC-14 §2 accounts 页转正 / F-G22~G28）
   - 登录态是「真校验」：读 platform_creds.state，标记文件存在 ≠ 还能发
   - 扫码登录诚实不可用：不提供扫码按钮，只保留固定 notice 说明
   - F-G28 窗口聚焦刷新：visibilitychange → visible 时重拉列表
   ========================================================================== */

import { useCallback, useEffect, useState } from 'react'
import { KeyRound, LogOut, ShieldCheck } from 'lucide-react'
import { Button, Card, Chip, ConfirmDialog, EmptyState, Input, Modal, Skeleton, Textarea, toast } from '@/components'
import { PageHead } from '@/features/shared/PageHead'
import { describeError } from '@/lib/gates'
import { accountsApi } from './api'
import { FORM_LABEL, loginState, type AccountItem, type AccountsResponse } from './types'

function hhmm(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function AccountsPage() {
  const [items, setItems] = useState<AccountItem[]>([])
  const [meta, setMeta] = useState<Pick<AccountsResponse, 'qr_login' | 'verify_notice'> | null>(null)
  const [loading, setLoading] = useState(true)
  const [errorText, setErrorText] = useState('')

  /* 录入凭证弹层 */
  const [credFor, setCredFor] = useState<AccountItem | null>(null)
  const [credAccount, setCredAccount] = useState('')
  const [credSecret, setCredSecret] = useState('')
  const [credSaving, setCredSaving] = useState(false)
  const [credError, setCredError] = useState('')
  /** secret 掩码（接口只回传掩码）；编辑时做占位说明而不是真值 */
  const [masked, setMasked] = useState<Record<string, string>>({})

  const [verifying, setVerifying] = useState<string | null>(null)
  const [logoutFor, setLogoutFor] = useState<AccountItem | null>(null)

  /* ---------------------------------------------------------- 数据加载 */

  const load = useCallback(async () => {
    try {
      const r = await accountsApi.list()
      setItems(r.items)
      setMeta({ qr_login: r.qr_login, verify_notice: r.verify_notice })
      setErrorText('')
    } catch (e) {
      setErrorText(describeError(e)) /* 页面静态错误条 + 重试；api 层 toast 不重复处理 */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  /* F-G28 窗口聚焦刷新：切回本标签页时重拉（后端有 60s 缓存，重拉很便宜） */
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') void load()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [load])

  /* ---------------------------------------------------------- 凭证 / 验证 / 登出 */

  const openCred = (item: AccountItem) => {
    setCredFor(item)
    setCredAccount(item.auth.account ?? '')
    setCredSecret('')
    setCredError('')
  }

  const closeCred = () => {
    setCredFor(null)
    setCredSecret('')
    setCredError('')
  }

  const saveCred = async () => {
    if (!credFor) return
    setCredSaving(true)
    setCredError('')
    try {
      const r = await accountsApi.saveCredential(credFor.platform, {
        account: credAccount.trim() || undefined,
        secret: credSecret.trim() || undefined,
      })
      if (r.unchanged) toast('未改动：secret 留空，保留原凭证', 'info')
      else toast('凭证已保存（加密存储），点「验证」更新登录态', 'ok')
      if (r.credential.secret_masked) {
        setMasked((m) => ({ ...m, [credFor.platform]: r.credential.secret_masked as string }))
      }
      closeCred()
      void load()
    } catch (e) {
      setCredError(describeError(e))
    } finally {
      setCredSaving(false)
    }
  }

  const verify = async (item: AccountItem) => {
    setVerifying(item.platform)
    try {
      const r = await accountsApi.verify(item.platform)
      /* message 必展示：含「本地校验」诚实说明 */
      toast(r.message, r.ok ? 'ok' : 'warn')
      void load()
    } catch {
      /* ApiError 已自动 toast */
    } finally {
      setVerifying(null)
    }
  }

  const doLogout = async () => {
    if (!logoutFor) return
    const target = logoutFor
    setLogoutFor(null)
    try {
      await accountsApi.logout(target.platform)
      toast(`已清除${target.display_name}的登录凭证与状态`, 'ok')
      void load()
    } catch {
      /* ApiError 已自动 toast（含 404 本来就没有记录） */
    }
  }

  /* ---------------------------------------------------------- 渲染 */

  return (
    <div className="view-pad">
      <PageHead
        title="账号登录"
        desc="登录态是「真校验」的：读本地凭证状态而不是标记文件；每次发布前还会再验一次。"
      />

      {meta ? (
        <div className="stack" style={{ gap: 8, marginBottom: 12 }}>
          <p className="sysfile" style={{ margin: 0 }}>
            {meta.qr_login.notice}
          </p>
          <p className="sysfile" style={{ margin: 0 }}>
            {meta.verify_notice}
          </p>
        </div>
      ) : null}

      {loading ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12 }}>
          {Array.from({ length: 7 }, (_, i) => (
            <Skeleton key={i} height={148} radius={14} />
          ))}
        </div>
      ) : null}

      {!loading && errorText ? (
        <div className="stack" style={{ gap: 10 }}>
          <p className="sysfile danger" style={{ whiteSpace: 'pre-line', margin: 0 }} role="alert">
            {errorText}
          </p>
          <div>
            <Button variant="primary" onClick={() => void load()}>
              重试
            </Button>
          </div>
        </div>
      ) : null}

      {!loading && !errorText && items.length === 0 ? (
        <EmptyState
          title="还没有拿到平台列表"
          description="后端没有返回任何平台卡片，可能是服务没起来或版本过旧。"
          actionLabel="重新加载"
          onAction={() => void load()}
        />
      ) : null}

      {!loading && !errorText && items.length > 0 ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12 }}>
          {items.map((item) => {
            const st = loginState(item)
            return (
              <div key={item.platform} data-testid={`acct-${item.platform}`}>
                <Card
                  title={item.display_name}
                  actions={
                    <Chip tone={st.tone} xs title={item.auth.message}>
                      {st.label}
                    </Chip>
                  }
                >
                <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                  {item.forms.map((f) => (
                    <Chip key={f} tone="outline" xs>
                      {FORM_LABEL[f] ?? f}
                    </Chip>
                  ))}
                </div>
                <p className="help" style={{ margin: '0 0 6px' }}>
                  标题 ≤ {item.title_max} 字 · 正文 ≤ {item.body_max} 字
                </p>
                <p className="help" style={{ margin: '0 0 6px' }}>
                  {item.auth.message}
                </p>
                <p className="help" style={{ margin: '0 0 6px' }}>
                  {item.auth.verified_at ? `最近验证 ${hhmm(item.auth.verified_at)}` : '从未验证'}
                  {item.auth.account ? ` · 账号 ${item.auth.account}` : ''}
                </p>
                {item.notice ? (
                  <p className="help" style={{ margin: '0 0 6px' }}>
                    {item.notice}
                  </p>
                ) : null}
                <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
                  <Button size="sm" icon={KeyRound} onClick={() => openCred(item)}>
                    录入凭证
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={ShieldCheck}
                    loading={verifying === item.platform}
                    onClick={() => void verify(item)}
                  >
                    验证
                  </Button>
                  <Button size="sm" variant="ghost" icon={LogOut} onClick={() => setLogoutFor(item)}>
                    登出
                  </Button>
                </div>
                </Card>
              </div>
            )
          })}
        </div>
      ) : null}

      {/* ------------------------------------------------ 录入凭证弹层 */}
      <Modal
        open={credFor != null}
        onClose={closeCred}
        title={`录入凭证 · ${credFor?.display_name ?? ''}`}
        sub="凭证加密存储在本机；secret 任何接口都只回传掩码"
        width={480}
        footer={
          <>
            <Button onClick={closeCred}>取消</Button>
            <Button variant="primary" loading={credSaving} onClick={() => void saveCred()}>
              保存凭证
            </Button>
          </>
        }
      >
        <div className="stack" style={{ gap: 10 }}>
          <Input
            label="账号（可选）"
            value={credAccount}
            placeholder="手机号 / 邮箱 / 用户名，仅用于展示"
            onChange={(e) => setCredAccount(e.target.value)}
          />
          <Textarea
            label="登录凭证 secret"
            help="留空保存=不覆盖已有凭证"
            rows={4}
            mono
            value={credSecret}
            placeholder={
              credFor && masked[credFor.platform]
                ? `已保存（${masked[credFor.platform]}），留空则不覆盖`
                : credFor?.has_credential
                  ? '已保存过凭证，留空保存=不覆盖'
                  : '粘贴该平台的 cookie / token / 密钥'
            }
            onChange={(e) => setCredSecret(e.target.value)}
          />
          {credError ? (
            <p className="sysfile danger" style={{ whiteSpace: 'pre-line', margin: 0 }} role="alert">
              {credError}
            </p>
          ) : null}
        </div>
      </Modal>

      {/* ------------------------------------------------ 登出二次确认 */}
      <ConfirmDialog
        open={logoutFor != null}
        danger
        title={`登出 ${logoutFor?.display_name ?? ''}`}
        okText="确认登出"
        onCancel={() => setLogoutFor(null)}
        onConfirm={() => void doLogout()}
      >
        <p style={{ margin: 0, fontSize: 13 }}>
          将清除{logoutFor?.display_name ?? ''}的登录凭证与状态，不可恢复。之后发布该平台会被登录态门禁拦下。
        </p>
      </ConfirmDialog>
    </div>
  )
}

export default AccountsPage
