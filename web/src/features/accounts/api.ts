/** SPEC-14 §1.1 · 账号域 API client（唯一出口）。 */

import { api } from '@/lib/api'
import type {
  AccountsResponse,
  CredentialResponse,
  LogoutResponse,
  VerifyResponse,
} from './types'

/** 写请求显式带 Content-Type：地基的跨站写中间件（SPEC-01 §8）要求。 */
const JSON_HEADERS = { 'Content-Type': 'application/json' } as const

export const accountsApi = {
  /** 7 平台卡（后端带 60s 登录态缓存；F-G28 聚焦刷新直接重拉即可） */
  list: () => api.get<AccountsResponse>('/accounts'),

  /** F-G25 录入凭证：secret 留空（undefined）且已有凭证 → {unchanged: true} */
  saveCredential: (platform: string, body: { account?: string; secret?: string }) =>
    api.post<CredentialResponse>(`/accounts/${platform}/credential`, body, { headers: JSON_HEADERS }),

  /** F-G24 登录态真校验（本地凭证校验，message 如实标注） */
  verify: (platform: string) =>
    api.post<VerifyResponse>(`/accounts/${platform}/verify`, {}, { headers: JSON_HEADERS }),

  /** F-G26 登出：清除凭证与登录态；无记录时 404 */
  logout: (platform: string) => api.del<LogoutResponse>(`/accounts/${platform}`),
}
