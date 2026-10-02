import { M2Placeholder } from '@/features/shared/M2Placeholder'

export function HotPage() {
  return (
    <M2Placeholder
      title="热点发现"
      desc="媒体 → 数据源 → 博主，三层下钻。收藏即入选题库，带来源可溯源。"
      primaryLabel="收藏 / 做成内容"
      willDo="7 源热榜聚合（抖音/微博/B站/小红书/知乎/头条/百度），支持缓存命中标注与深度加载的代价确认。"
      blockedBy="后端 /api/hot 尚未提供；热榜抓取属 M2。"
      fallbackTo={{ to: '/capability', label: '先去能力地图' }}
    />
  )
}

export default HotPage
