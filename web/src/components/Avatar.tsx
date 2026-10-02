export type AvatarTone = 'default' | 'accent' | 'warn'

export type AvatarProps = {
  /** 1–2 个字的文字标识，如「效率」「Mr」 */
  label: string
  tone?: AvatarTone
  /** lg = 38px 账号方块（账号登录页） */
  size?: 'sm' | 'md' | 'lg'
  title?: string
  className?: string
}

const TONE: Record<AvatarTone, string> = { default: '', accent: 'g', warn: 'w' }

/** 头像：圆角方块 + 渐变底 + 白字（原型 .avatar） */
export function Avatar({ label, tone = 'default', size = 'md', title, className = '' }: AvatarProps) {
  return (
    <span
      className={['avatar', TONE[tone], size === 'lg' ? 'lg' : '', className].filter(Boolean).join(' ')}
      title={title ?? label}
      aria-hidden
    >
      {label.slice(0, 2)}
    </span>
  )
}

export default Avatar
