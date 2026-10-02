/** SPEC-11 · 数据复盘页（M2-3a 占位转正）；SPEC-12 §3 策划域 P3 三工具；SPEC-15 M5 数据录入。
 *
 * 顶部是七个即席分析/策划工具（账号诊断 primary · 内容策略 · 受众画像 · 竞品分析 ·
 * 营销策划 · 直播策划 · 商单方案）；底部「数据录入」区是真实回收的第一步：
 * 平台不提供公开数据接口，快照/表现/台账全部手工抄录，看板与复盘只吃真实录入。
 */

import { useCallback, useEffect, useState } from 'react'
import { CalendarRange, ClipboardList, Gauge, Handshake, ListChecks, Sparkles, Tv, Users } from 'lucide-react'
import { Button, Card, Skeleton } from '@/components'
import { PageHead } from '@/features/shared/PageHead'
import { AudienceDialog } from './AudienceDialog'
import { attributionApi } from './api'
import { CompetitorDialog } from './CompetitorDialog'
import { DiagnoseDialog } from './DiagnoseDialog'
import { MetricDialog } from './MetricDialog'
import { PlanDialog } from './PlanDialog'
import { RoiDialog } from './RoiDialog'
import { SnapshotDialog } from './SnapshotDialog'
import { StrategyDialog } from './StrategyDialog'
import type { PlanKind } from './api'
import type { RoiSummary, Snapshot } from './types'

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
  const [planKind, setPlanKind] = useState<PlanKind | null>(null)
  const [snapshotOpen, setSnapshotOpen] = useState(false)
  const [metricOpen, setMetricOpen] = useState(false)
  const [roiOpen, setRoiOpen] = useState(false)

  // 录入区卡内小字：undefined=加载中，null=还没录过
  const [latestSnapshot, setLatestSnapshot] = useState<Snapshot | null | undefined>(undefined)
  const [roi, setRoi] = useState<RoiSummary | null>(null)

  const refreshEntry = useCallback(() => {
    attributionApi
      .listSnapshots()
      .then((r) => setLatestSnapshot(r.items?.[0] ?? null))
      .catch(() => setLatestSnapshot(null))
    attributionApi
      .roiSummary()
      .then(setRoi)
      .catch(() => setRoi({ insufficient: true }))
  }, [])

  useEffect(() => {
    refreshEntry()
  }, [refreshEntry])

  const PLANS: { kind: PlanKind; icon: typeof Tv; title: string; desc: string }[] = [
    {
      kind: 'campaign',
      icon: CalendarRange,
      title: '营销活动策划',
      desc: '节日 / 大促 / 新品发布的完整方案：目标、创意、排期、分工、预算 KPI。',
    },
    {
      kind: 'liveplan',
      icon: Tv,
      title: '直播策划',
      desc: '流程脚本、关键话术、互动设计与风险预案，按时长出时间轴。',
    },
    {
      kind: 'sponsorship',
      icon: Handshake,
      title: '商单方案',
      desc: '贴品牌需求，出合作提案：解读、创意、交付物、报价逻辑与谈判边界。',
    },
  ]

  const ENTRY_CARDS = [
    {
      key: 'snapshot',
      icon: Gauge,
      title: '账号快照',
      desc: '定期抄创作中心的粉丝数 / 累计获赞 / 作品数，攒出增长曲线。',
      small:
        latestSnapshot === undefined ? null : latestSnapshot === null ? (
          '还没录过'
        ) : (
          `最近一条：${latestSnapshot.captured_at} · ${latestSnapshot.platform} · 粉丝 ${latestSnapshot.followers}`
        ),
      actionLabel: '录入快照',
      onOpen: () => setSnapshotOpen(true),
    },
    {
      key: 'metric',
      icon: ListChecks,
      title: '内容表现',
      desc: '发布后到创作者中心抄播放 / 点赞 / 评论 / 转发，回填到具体发布记录。',
      small: '下拉自动带出最近的发布记录（平台 · 标题 · 时间）',
      actionLabel: '录入表现',
      onOpen: () => setMetricOpen(true),
    },
    {
      key: 'roi',
      icon: ClipboardList,
      title: '投入台账',
      desc: '每篇内容花的时间 / 钱记一笔——ROI 只算真实台账，不编产出比。',
      small:
        roi === null
          ? '还没有投入记录'
          : roi.insufficient
            ? '还没有投入记录'
            : `近 ${roi.days ?? 30} 天：${roi.total_hours} 小时 / ${roi.total_amount} 元`,
      actionLabel: '记一笔',
      onOpen: () => setRoiOpen(true),
    },
  ]

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
        <div className="stack" style={{ gap: 6 }}>
          <b style={{ fontSize: 13 }}>平台数据从哪来</b>
          <p className="mut" style={{ margin: 0, fontSize: 12.5 }}>
            平台不提供公开数据接口——表现数据靠你从创作者中心抄录到这里，看板与复盘只吃真实录入。
          </p>
        </div>
      </Card>

      <div
        style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12 }}
        data-testid="plan-grid"
      >
        {PLANS.map((p) => (
          <Card key={p.kind} title={p.title} tight>
            <div className="stack" style={{ gap: 10 }}>
              <p style={{ margin: 0, fontSize: 12.5, color: 'var(--ink-2)', minHeight: 36 }}>
                {p.desc}
              </p>
              <div>
                <Button
                  size="sm"
                  icon={p.icon}
                  aria-label={`策划：${p.title}`}
                  onClick={() => setPlanKind(p.kind)}
                >
                  策划
                </Button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <section className="stack" style={{ gap: 12 }} aria-label="数据录入" data-testid="entry-section">
        <div>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>数据录入（真实回收的第一步）</h2>
          <p className="mut" style={{ margin: '2px 0 0', fontSize: 12.5 }}>
            三张表全部手工录入；工作台看板与本页复盘只画这里的数据。
          </p>
        </div>
        <div
          style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12 }}
          data-testid="entry-grid"
        >
          {ENTRY_CARDS.map((c) => (
            <Card key={c.key} title={c.title} tight>
              <div className="stack" style={{ gap: 10 }}>
                <p style={{ margin: 0, fontSize: 12.5, color: 'var(--ink-2)', minHeight: 36 }}>{c.desc}</p>
                <div className="mut2" style={{ fontSize: 'var(--fs-help)' }}>
                  {c.small === null ? <Skeleton width="80%" height={14} /> : c.small}
                </div>
                <div>
                  <Button size="sm" icon={c.icon} aria-label={`录入：${c.title}`} onClick={c.onOpen}>
                    {c.actionLabel}
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </section>

      <StrategyDialog open={strategyOpen} onClose={() => setStrategyOpen(false)} />
      <AudienceDialog open={audienceOpen} onClose={() => setAudienceOpen(false)} />
      <CompetitorDialog open={competitorOpen} onClose={() => setCompetitorOpen(false)} />
      <DiagnoseDialog open={diagnoseOpen} onClose={() => setDiagnoseOpen(false)} />
      <PlanDialog
        open={planKind !== null}
        kind={planKind ?? 'campaign'}
        onClose={() => setPlanKind(null)}
      />
      <SnapshotDialog
        open={snapshotOpen}
        onClose={() => setSnapshotOpen(false)}
        onSaved={refreshEntry}
      />
      <MetricDialog open={metricOpen} onClose={() => setMetricOpen(false)} onSaved={refreshEntry} />
      <RoiDialog open={roiOpen} onClose={() => setRoiOpen(false)} onSaved={refreshEntry} />
    </div>
  )
}

export default AnalyticsPage
