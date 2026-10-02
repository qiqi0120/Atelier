import { Clapperboard, Flame, Scissors, Video } from 'lucide-react'

export type SceneSuggestionsProps = {
  /** 只填入输入框，**绝不自动发送**（UI-SPEC 规则 1） */
  onPick: (text: string) => void
}

const SCENES: { icon: typeof Flame; name: string; desc: string; text: string }[] = [
  { icon: Flame, name: '追热点', desc: '抓今天热榜第一条，直接出图文', text: '把今天的热榜第一条写成小红书图文' },
  { icon: Scissors, name: '拆爆款', desc: '粘贴对标内容，6 段式拆解 + 出选题', text: '拆解这条爆款：' },
  { icon: Clapperboard, name: '去 AI 感', desc: '五维打分对比，直接给改后版本', text: '把这条内容去 AI 感改写' },
  { icon: Video, name: '出视频', desc: '主题 → 竖版成片，含配音字幕', text: '帮我做「一键成片」' },
]

/** 空态 4 个场景卡（PRD F-B10）。点了只填输入框。 */
export function SceneSuggestions({ onPick }: SceneSuggestionsProps) {
  return (
    <div className="scn" style={{ maxWidth: 560, margin: '18px auto 0' }}>
      {SCENES.map((s) => {
        const Icon = s.icon
        return (
          <button type="button" key={s.name} onClick={() => onPick(s.text)}>
            <b>
              <Icon size={14} />
              {s.name}
            </b>
            <span>{s.desc}</span>
          </button>
        )
      })}
    </div>
  )
}

export default SceneSuggestions
