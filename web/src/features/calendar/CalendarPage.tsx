import { M2Placeholder } from '@/features/shared/M2Placeholder'

export function CalendarPage() {
  return (
    <M2Placeholder
      title="内容日历"
      desc="内容条目与平台活动分开标记，状态流转：选题 → 草稿 → 待发 → 已发。"
      primaryLabel="生成近 14 天建议"
      willDo="月视图排期，内容条目与平台活动（斜纹只读）分开标记，状态可流转。"
      blockedBy="后端 /api/calendar 尚未提供；排期数据属 M2。日历格样式已在全局 CSS 备好。"
      fallbackTo={{ to: '/topics', label: '先去选题库' }}
    />
  )
}

export default CalendarPage
