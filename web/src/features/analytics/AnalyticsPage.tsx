import { M2Placeholder } from '@/features/shared/M2Placeholder'

export function AnalyticsPage() {
  return (
    <M2Placeholder
      title="数据复盘"
      desc="回收失败会保留上次快照，不会把已有数据清空。"
      primaryLabel="回收数据"
      willDo="多平台数据回收 + 增长对比 + 内容表现表 + 评论洞察，结论先给用户确认再沉淀回画像。"
      blockedBy="后端 /api/analytics 尚未提供；平台数据回收属 M2。"
      fallbackTo={{ to: '/library', label: '先看内容库' }}
    />
  )
}

export default AnalyticsPage
