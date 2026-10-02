import { ChevronsUpDown } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Avatar, toast } from '@/components'
import { useAtelier } from '@/lib/store'

/** 侧边栏底部常驻画像切换器（UI-SPEC §3：头像 + 账号名 + 平台 + 生效状态点） */
export function ProfileSwitcher() {
  const navigate = useNavigate()
  const profile = useAtelier((s) => s.profile)
  const profiles = useAtelier((s) => s.profiles)
  const setProfile = useAtelier((s) => s.setProfile)

  if (!profile) {
    return (
      <button type="button" className="prof-pick" onClick={() => navigate('/profile')}>
        <Avatar label="＋" />
        <span className="t">
          <b>还没有画像</b>
          <span>点这里建一个</span>
        </span>
      </button>
    )
  }

  return (
    <button
      type="button"
      className="prof-pick"
      title={profile.generalMode ? '通用模式：不注入画像' : `当前画像：${profile.name}`}
      onClick={() => {
        // M1 只有占位画像：轮换演示，等 Wave 2 接 /api/profiles
        const idx = profiles.findIndex((p) => p?.id === profile.id)
        const next = profiles[(idx + 1) % Math.max(1, profiles.length)]
        if (next) {
          setProfile(next)
          toast(`已切换画像：${next.name}`, 'ok')
        }
        navigate('/profile')
      }}
    >
      <Avatar label={profile.name.slice(0, 2)} tone="accent" />
      <span className="t">
        <b>{profile.name}</b>
        <span>
          <i className={`live-dot ${profile.generalMode ? 'warn' : ''}`} />
          {profile.generalMode ? '通用模式 · 不注入' : profile.platforms.join(' · ')}
        </span>
      </span>
      <ChevronsUpDown size={14} className="chev" style={{ color: 'var(--muted)' }} />
    </button>
  )
}

export default ProfileSwitcher
