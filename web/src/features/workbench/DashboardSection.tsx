/** F-H2 创作数据看板（工作台页内 section，不新增路由）。
 *
 * 三态齐备：loading Skeleton / error 静态条（handled，不重复 toast）/ insufficient EmptyState。
 * 粉丝差值由前端对 snapshots 序列**自己算首尾差**，不引图表库，折线是手写 SVG polyline。
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, EmptyState, Select, Skeleton, Table } from '@/components'
import type { SelectOption } from '@/components'
import { describeError } from '@/lib/gates'
import { workbenchApi } from './api'
import type { DashboardResponse, SnapshotPoint } from './types'

const PLATFORM_OPTIONS: SelectOption[] = [
  { value: '', label: '全部平台' },
  { value: 'xhs', label: 'xhs' },
  { value: 'dy', label: 'dy' },
  { value: 'gzh', label: 'gzh' },
  { value: 'ks', label: 'ks' },
  { value: 'zhihu', label: 'zhihu' },
  { value: 'bilibili', label: 'bilibili' },
  { value: 'wcs', label: 'wcs' },
]

const DAY_OPTIONS: SelectOption[] = [
  { value: '7', label: '近 7 天' },
  { value: '30', label: '近 30 天' },
  { value: '90', label: '近 90 天' },
]

/** 粉丝快照折线：空序列不画；单点画一个圆；y 轴按 min/max 归一。 */
function Sparkline({ points }: { points: SnapshotPoint[] }) {
  if (points.length === 0) return null
  const W = 100
  const H = 32
  const PAD = 3
  const values = points.map((p) => p.followers)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const step = points.length > 1 ? (W - PAD * 2) / (points.length - 1) : 0
  const coords = points.map((p, i) => {
    const x = PAD + step * i
    const y = H - PAD - ((p.followers - min) / span) * (H - PAD * 2)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      style={{ width: '100%', height: 56, display: 'block' }}
      role="img"
      aria-label={`粉丝快照折线，共 ${points.length} 条`}
    >
      {points.length === 1 ? (
        <circle cx={coords[0]?.split(',')[0]} cy={coords[0]?.split(',')[1]} r={2.5} fill="var(--accent)" />
      ) : (
        <polyline
          points={coords.join(' ')}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={2}
          vectorEffect="non-scaling-stroke"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      )}
    </svg>
  )
}

/** 首尾差：正绿负红中性灰（语义色只做状态）。 */
function FollowerDelta({ delta }: { delta: number }) {
  if (delta > 0) return <span className="delta up">↑ {delta}</span>
  if (delta < 0) return <span className="delta dn">↓ {Math.abs(delta)}</span>
  return <span className="delta" style={{ color: 'var(--ink-3)' }}>持平</span>
}

function MetricCell({ label, value }: { label: string; value: number }) {
  return (
    <div className="kpi">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  )
}

export function DashboardSection() {
  const navigate = useNavigate()
  const [platform, setPlatform] = useState('')
  const [days, setDays] = useState('30')
  const [data, setData] = useState<DashboardResponse | null>(null)
  const [errorText, setErrorText] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    setLoading(true)
    workbenchApi
      .dashboard(platform, Number(days), { handled: true })
      .then((d) => {
        if (!alive) return
        setData(d)
        setErrorText('')
        setLoading(false)
      })
      .catch((e) => {
        if (!alive) return
        setData(null)
        setErrorText(describeError(e))
        setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [platform, days])

  const snapshots = data?.snapshots ?? []
  const latest = snapshots.length > 0 ? snapshots[snapshots.length - 1] : null
  const first = snapshots.length > 0 ? snapshots[0] : null
  const followerDelta = latest && first ? latest.followers - first.followers : null
  const metrics = data?.metrics_by_day ?? []
  const metricTotals = metrics.reduce(
    (acc, m) => ({
      views: acc.views + m.views,
      likes: acc.likes + m.likes,
      comments: acc.comments + m.comments,
      shares: acc.shares + m.shares,
    }),
    { views: 0, likes: 0, comments: 0, shares: 0 },
  )

  return (
    <section id="dashboard" className="stack" style={{ gap: 12 }} aria-label="创作数据看板">
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>创作数据看板</h3>
        <div className="row" style={{ gap: 8 }}>
          <Select
            aria-label="看板平台"
            sizeSm
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
            options={PLATFORM_OPTIONS}
          />
          <Select
            aria-label="看板时间窗"
            sizeSm
            value={days}
            onChange={(e) => setDays(e.target.value)}
            options={DAY_OPTIONS}
          />
        </div>
      </div>

      {loading ? (
        <div className="stack" style={{ gap: 12 }}>
          <div className="grid2">
            <Card>
              <div className="stack" style={{ gap: 8 }}>
                <Skeleton width="40%" height={16} />
                <Skeleton width="70%" height={48} />
              </div>
            </Card>
            <Card>
              <div className="stack" style={{ gap: 8 }}>
                <Skeleton width="40%" height={16} />
                <Skeleton width="70%" height={48} />
              </div>
            </Card>
          </div>
          <Card>
            <Skeleton width="100%" height={72} />
          </Card>
        </div>
      ) : errorText ? (
        <Card>
          <p className="sysfile danger" style={{ margin: 0 }} role="alert">
            {errorText}
          </p>
        </Card>
      ) : data?.insufficient ? (
        <Card>
          <EmptyState
            title="看板只画真实录入的数据"
            description={data.message}
            actionLabel="去录入数据"
            onAction={() => navigate('/analytics')}
          />
        </Card>
      ) : (
        <div className="stack" style={{ gap: 14 }}>
          <div className="grid2" style={{ alignItems: 'stretch' }}>
            <Card title={`粉丝快照（近 ${data?.days ?? 30} 天）`}>
              {latest ? (
                <div className="stack" style={{ gap: 8 }}>
                  <div className="row" style={{ gap: 10, alignItems: 'baseline' }}>
                    <b style={{ fontSize: 24, fontFamily: 'var(--mono)' }}>{latest.followers}</b>
                    {followerDelta !== null ? <FollowerDelta delta={followerDelta} /> : null}
                    <span className="mut2" style={{ fontSize: 'var(--fs-help)' }}>
                      {first?.captured_at} → {latest.captured_at}
                    </span>
                  </div>
                  <Sparkline points={snapshots} />
                </div>
              ) : (
                <div className="stack" style={{ gap: 8 }}>
                  <p className="mut" style={{ margin: 0, fontSize: 12.5 }}>
                    这个窗口内还没有快照——差值与折线从第一条快照开始画，不编数字。
                  </p>
                  <Button size="sm" variant="ghost" onClick={() => navigate('/analytics')}>
                    去录入快照
                  </Button>
                </div>
              )}
            </Card>
            <Card title="表现合计（按天求和）">
              {metrics.length > 0 ? (
                <div className="stat-row" style={{ gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
                  <MetricCell label="浏览" value={metricTotals.views} />
                  <MetricCell label="点赞" value={metricTotals.likes} />
                  <MetricCell label="评论" value={metricTotals.comments} />
                  <MetricCell label="转发" value={metricTotals.shares} />
                </div>
              ) : (
                <p className="mut" style={{ margin: 0, fontSize: 12.5 }}>
                  还没有表现记录——发布后到创作者中心抄数字，回填到「数据复盘 → 内容表现」。
                </p>
              )}
            </Card>
          </div>
          <Card title="Top 内容（按浏览）" tight>
            <Table
              columns={[
                { key: 'title', title: '标题' },
                { key: 'platform', title: '平台' },
                { key: 'views', title: '浏览', numeric: true },
                { key: 'likes', title: '点赞', numeric: true },
              ]}
              rows={data?.top_contents ?? []}
              rowKey={(r, i) => `${r.platform}-${r.title}-${i}`}
              empty="这个窗口内没有表现记录"
            />
          </Card>
        </div>
      )}
    </section>
  )
}

export default DashboardSection
