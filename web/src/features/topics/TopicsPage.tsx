import { M2Placeholder } from '@/features/shared/M2Placeholder'

export function TopicsPage() {
  return (
    <M2Placeholder
      title="选题库"
      desc="待做 / 进行中 / 已完成。拖卡片改状态，点卡片看角度与来源。"
      primaryLabel="新建选题"
      willDo="三列看板 + 拖拽改状态 + 7 维评分（流量/匹配/差异/时效/变现/成本/风险）。"
      blockedBy="后端 /api/topics 尚未提供；选题持久化属 M2。"
      fallbackTo={{ to: '/hot', label: '先去热点发现' }}
    />
  )
}

export default TopicsPage
