import { M2Placeholder } from '@/features/shared/M2Placeholder'

export function AccountsPage() {
  return (
    <M2Placeholder
      title="账号登录"
      desc="登录态是「真校验」的：标记文件存在 ≠ 还能发。每次发布前会再验一次。"
      primaryLabel="扫码 / 凭证"
      willDo="5 个平台扫码登录 + 公众号凭证登录，扫码状态按「等待扫码 → 已扫码待确认 → 登录中 → 成功」四段式推进。"
      blockedBy="后端 /api/accounts 尚未提供；平台登录态属 M2（风控风险高，需真机验证）。"
      fallbackTo={{ to: '/settings', label: '先去设置配密钥' }}
    />
  )
}

export default AccountsPage
