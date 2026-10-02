/** SPEC-11 · 数据复盘页（M2-3a，占位页转正）。
 *
 * 四个即席分析工具：账号诊断（primary，诚实模式）· 内容策略 · 受众画像 · 竞品分析。
 * 平台数据回收 / 数据看板（F-H2）属 M5，本页不装样子。
 */

import { useState } from 'react'
import { Gauge, ListChecks, Sparkles, Users } from 'lucide-react'
import { Button, Card, EmptyState } from '@/components'
import { PageHead } from '@/features/shared/PageHead'
import { AudienceDialog } from './AudienceDialog'
import { CompetitorDialog } from './CompetitorDialog'
import { DiagnoseDialog } from './DiagnoseDialog'
import { StrategyDialog } from './StrategyDialog'

const TOOLS = [
  {
    key: 'strategy',
    icon: Sparkles,
    title: '内容策略',
    desc: '内容支柱架构、受众路径、90 天节奏、KPI——四段式，基于画像生成。',
  },
  {
    key: 'audience',
    icon: Users,
    title: '受众画像卡',
    desc: '目标人群一句话 + 痛点、典型场景、内容偏好、避坑提醒。',
  },
  {
    key: 'competitor',
    icon: ListChecks,
    title: '竞品分析',
    desc: '粘贴竞品内容，反推 TA 的选题、格式与爆款规律；选题可一键入库。',
  },
] as const

export function AnalyticsPage() {
  const [strategyOpen, setStrategyOpen] = useState(false)
  const [audienceOpen, setAudienceOpen] = useState(false)
  const [competitorOpen, setCompetitorOpen] = useState(false)
  const [diagnoseOpen, setDiagnoseOpen] = useState(false)

  return (
    <div className="view-pad">
      <PageHead
        title="数据复盘"
        desc="基于本地真实记录做分析——数据不足会如实说，不编分数。"
        actions={
          <Button variant="primary" icon={Gauge} onClick={() => setDiagnoseOpen(true)}>
            账号诊断
          </Button>
        }
      />

      <div
        style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12 }}
        data-testid="insights-grid"
      >
        {TOOLS.map((tool) => (
          <Card key={tool.key} title={tool.title} tight>
            <div className="stack" style={{ gap: 10 }}>
              <p style={{ margin: 0, fontSize: 12.5, color: 'var(--ink-2)', minHeight: 36 }}>
                {tool.desc}
              </p>
              <div>
                <Button
                  size="sm"
                  icon={tool.icon}
                  aria-label={`生成：${tool.title}`}
                  onClick={() => {
                    if (tool.key === 'strategy') setStrategyOpen(true)
                    if (tool.key === 'audience') setAudienceOpen(true)
                    if (tool.key === 'competitor') setCompetitorOpen(true)
                  }}
                >
                  生成
                </Button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Card tight>
        <EmptyState
          icon={<Gauge size={22} />}
          title="平台数据回收（播放/涨粉/互动）属 M5"
          description="当前的分析全部基于本地真实记录：发布记录、草稿、选题流转。等 M4 打通真实发布、M5 回收平台数据后，这里会有增长对比与内容表现表。"
        />
      </Card>

      <StrategyDialog open={strategyOpen} onClose={() => setStrategyOpen(false)} />
      <AudienceDialog open={audienceOpen} onClose={() => setAudienceOpen(false)} />
      <CompetitorDialog open={competitorOpen} onClose={() => setCompetitorOpen(false)} />
      <DiagnoseDialog open={diagnoseOpen} onClose={() => setDiagnoseOpen(false)} />
    </div>
  )
}

export default AnalyticsPage
