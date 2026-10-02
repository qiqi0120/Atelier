import { create } from 'zustand'
import type { Memory, Profile } from './types'

/** 当前生效画像（SPEC-01 §6：画像以消息前缀内联，不落全局文件） */
export type ActiveProfile = {
  id: string
  name: string
  platforms: string[]
  /** 通用模式：本轮不注入画像 */
  generalMode: boolean
  completeness: number
} | null

export type AtelierState = {
  profile: ActiveProfile
  profiles: ActiveProfile[]
  memories: Memory[]
  sessionId: string | null
  /** 跨页预置的 prompt（能力卡 / 热点「做成内容」只填入，不自动发送） */
  draftPrompt: string
  /** 每次填入自增，供对话页判断是否需要聚焦 */
  draftSeq: number
  setProfile: (p: ActiveProfile) => void
  setProfiles: (list: ActiveProfile[]) => void
  setMemories: (m: Memory[]) => void
  setSessionId: (id: string | null) => void
  fillPrompt: (text: string) => void
  clearPrompt: () => void
}

export const MOCK_PROFILE: ActiveProfile = {
  id: 'ai-efficiency',
  name: 'AI 效率观察',
  platforms: ['小红书', '抖音', '公众号'],
  generalMode: false,
  completeness: 86,
}

/** 占位数据：M1 用原型同款画像，等 Wave 2 接上 /api/profiles 后替换 */
export const MOCK_PROFILES: ActiveProfile[] = [
  MOCK_PROFILE,
  { id: 'coffee', name: '咖啡探店日记', platforms: ['小红书', '抖音'], generalMode: false, completeness: 62 },
]

export const useAtelier = create<AtelierState>((set) => ({
  profile: MOCK_PROFILE,
  profiles: MOCK_PROFILES,
  memories: [],
  sessionId: null,
  draftPrompt: '',
  draftSeq: 0,
  setProfile: (profile) => set({ profile }),
  setProfiles: (profiles) => set({ profiles }),
  setMemories: (memories) => set({ memories }),
  setSessionId: (sessionId) => set({ sessionId }),
  fillPrompt: (draftPrompt) => set((s) => ({ draftPrompt, draftSeq: s.draftSeq + 1 })),
  clearPrompt: () => set({ draftPrompt: '' }),
}))

/** 把 Profile 模型压成侧栏切换器需要的摘要 */
export function toActive(p: Profile): ActiveProfile {
  const vals = [p.identity, p.style, p.audience, p.platform_rules, p.preferences, p.memories.length]
  const filled = vals.filter((v) => (typeof v === 'number' ? v > 0 : v.trim().length > 0)).length
  return {
    id: p.id,
    name: p.name,
    platforms: p.platforms,
    generalMode: p.general_mode,
    completeness: Math.round((filled / vals.length) * 100),
  }
}
