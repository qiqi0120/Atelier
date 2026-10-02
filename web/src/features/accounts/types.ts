/** =============================================================================
   账号登录中心 · 类型与登录态推导（SPEC-14 §1.1 / F-G22~G28）
   后端契约：GET /api/accounts（7 平台）+ credential / verify / DELETE。
   ★ 登录态是「真校验」结果（读 platform_creds.state），不是固定文案。
   ========================================================================== */

export type AccountAuth = {
  platform: string
  logged_in: boolean
  account: string | null
  need_sms: boolean
  message: string
  verified_at: string | null
  /** /api/accounts 集成时补的机器可读状态（凭 state 上色，message 文案只做兜底） */
  state?: 'unknown' | 'valid' | 'expired'
}

export type AccountItem = {
  platform: string
  display_name: string
  forms: string[]
  title_max: number
  body_max: number
  has_credential: boolean
  /** 已录入凭证时的掩码（如 sk-****abcd）；未录入为空串 */
  secret_masked?: string
  auth: AccountAuth
  /** ks/zhihu/bilibili/wcs 四个新平台才有（「上限按公开资料设定」） */
  notice: string
}

export type AccountsResponse = {
  items: AccountItem[]
  total: number
  qr_login: { supported: boolean; notice: string }
  verify_notice: string
}

export type CredentialInfo = {
  account: string
  state: 'unknown' | 'valid' | 'expired'
  verified_at: string
  /** secret 永不回传，只有掩码 */
  secret_masked?: string
}

export type CredentialResponse = {
  ok: boolean
  /** secret 留空且已有凭证 → true（UI 显示「未改动」） */
  unchanged: boolean
  credential: CredentialInfo
}

export type VerifyResponse = {
  ok: boolean
  state: 'valid' | 'expired'
  verified_at: string
  auth: AccountAuth
  /** 必展示，含「本地校验」诚实说明 */
  message: string
}

export type LogoutResponse = {
  ok: boolean
  platform: string
  logged_out: boolean
}

/** 形态 → 中文（image→图文 / video→视频 / text→文字） */
export const FORM_LABEL: Record<string, string> = {
  image: '图文',
  video: '视频',
  text: '文字',
}

export type LoginState = {
  tone: 'accent' | 'danger' | 'warn'
  label: string
}

/**
 * 登录态三色标：logged_in→accent「已登录」/ state=expired→danger「已过期」/ 其余 warn。
 * 后端已在 /api/accounts 的 auth 里补机器可读 state（SPEC-14 §1.1 集成修订）；
 * message 文案判定保留作兜底。
 */
export function loginState(item: AccountItem): LoginState {
  if (item.auth.logged_in) return { tone: 'accent', label: '已登录' }
  if (item.auth.state === 'expired' || item.auth.message.includes('已过期')) {
    return { tone: 'danger', label: '已过期' }
  }
  return { tone: 'warn', label: '未验证或未登录' }
}
