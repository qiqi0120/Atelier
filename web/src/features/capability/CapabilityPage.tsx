/** SPEC-04 §5 · 能力地图页（照 design/prototype-v1.html 的 `#v-capability`）。
 *
 * 数据全部来自 GET /api/capabilities（capabilities.toml 是唯一事实源），
 * 页面不再内置任何硬编码目录。行为要点：
 * - F-C4：点能力项 → fillPrompt(触发语) → navigate('/chat') → toast，**绝不自动发送**
 * - 分组导航 + 搜索 + 成熟度筛选形态保留；四态齐备（loading / error / 空 / 数据）
 * - 后端分组为空 → EmptyState 引导去技能库
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, Search } from 'lucide-react'
import { Button, Chip, EmptyState, Input, Skeleton, Tabs, toast } from '@/components'
import { capabilityApi } from './api'
import { capabilityIcon } from './icons'
import { MATURITY_LABEL } from '@/lib/types'
import type { CapabilitiesResponse } from '@/lib/types'
import { useAtelier } from '@/lib/store'
import { PageHead } from '@/features/shared/PageHead'
import { describeError } from '@/lib/gates'

const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'ready', label: '可立即用' },
  { key: 'needcfg', label: '需配置' },
]

export function CapabilityPage() {
  const navigate = useNavigate()
  const fillPrompt = useAtelier((s) => s.fillPrompt)
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState('all')
  const [data, setData] = useState<CapabilitiesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [errorText, setErrorText] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setErrorText('')
    try {
      setData(await capabilityApi.capabilities())
    } catch (e) {
      // api 层已 toast，这里只落状态条
      setErrorText(describeError(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const groups = useMemo(() => {
    const kw = q.trim().toLowerCase()
    return (data?.groups ?? [])
      .map((g) => ({
        ...g,
        items: g.items.filter((c) => {
          if (kw && !(`${c.name}${c.trigger}`.toLowerCase().includes(kw))) return false
          if (filter === 'ready') return c.maturity === 'v0' || c.maturity === 'v1'
          if (filter === 'needcfg') return c.maturity === 'v2' || c.maturity === 'v3'
          return true
        }),
      }))
      .filter((g) => g.items.length > 0)
  }, [data, q, filter])

  // 交互规则 1：点卡片只填入输入框，绝不自动发送（F-C4）
  const fill = (trigger: string) => {
    fillPrompt(trigger)
    navigate('/chat')
    toast('已填入输入框，确认后点发送', 'ok')
  }

  const isEmpty = !loading && !errorText && groups.length === 0
  const hasAny = (data?.total ?? 0) > 0

  return (
    <div className="view-pad">
      <PageHead
        title="能力地图"
        desc="按「你要的结果」分组，不按文件格式。点一下填进输入框，你自己决定什么时候发。"
        actions={
          <>
            <Input
              sizeSm
              placeholder="搜索能力名…"
              value={q}
              style={{ width: 180 }}
              onChange={(e) => setQ(e.target.value)}
              aria-label="搜索能力名"
            />
            <Tabs items={FILTERS} value={filter} onChange={setFilter} ariaLabel="能力筛选" />
          </>
        }
      />

      {errorText ? (
        <div className="card card-b" style={{ marginBottom: 14 }}>
          <p className="sysfile danger" role="alert">
            {errorText}
          </p>
          <Button style={{ marginTop: 10 }} onClick={() => void load()}>
            重试
          </Button>
        </div>
      ) : null}

      {loading ? (
        <div className="stack" style={{ gap: 14 }} aria-busy>
          <Skeleton height={22} width={200} />
          <div className="cap-items">
            {Array.from({ length: 8 }, (_, i) => (
              <div className="card card-b" key={i} style={{ padding: 14 }}>
                <Skeleton height={15} width="42%" />
                <div style={{ height: 8 }} />
                <Skeleton height={12} width="86%" />
              </div>
            ))}
          </div>
        </div>
      ) : isEmpty ? (
        hasAny ? (
          <EmptyState
            title={`没有匹配「${q}」的能力`}
            description="换个说法，或清空搜索看全部能力。"
            actionLabel="清空搜索"
            onAction={() => {
              setQ('')
              setFilter('all')
            }}
          />
        ) : (
          <EmptyState
            title="能力地图还是空的"
            description="skills/ 目录下还没有 SKILL.md。先去技能库看看有哪些技能可装。"
            actionLabel="去技能库"
            onAction={() => navigate('/skills')}
          />
        )
      ) : (
        groups.map((g) => (
          <div className="cap-grp" key={g.name}>
            <div className="cap-grp-h">
              <h3>{g.name}</h3>
              <span className="mut" style={{ fontSize: 'var(--fs-sub)' }}>
                {g.desc}
              </span>
              <div className="sp">
                <Chip tone="outline">{g.items.length} 项能力</Chip>
              </div>
            </div>
            <div className="cap-items">
              {g.items.map((c) => {
                const Icon = capabilityIcon(c.icon)
                return (
                  <button
                    type="button"
                    className="cap"
                    key={c.id}
                    onClick={() => fill(c.trigger || `帮我做「${c.name}」`)}
                  >
                    <div className="top">
                      <span className="ci">
                        <Icon size={14} strokeWidth={1.9} />
                      </span>
                      <h4>{c.name}</h4>
                    </div>
                    <div className="trig">{c.trigger}</div>
                    <div className="foot">
                      <span className={`mature ${c.maturity}`}>{MATURITY_LABEL[c.maturity]}</span>
                      <span className="go">
                        填入输入框
                        <Check size={11} />
                      </span>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>
        ))
      )}

      {!loading && !errorText && hasAny ? (
        <div className="card card-b" style={{ marginTop: 6, display: 'flex', gap: 10, alignItems: 'center' }}>
          <Search size={13} style={{ color: 'var(--muted)' }} />
          <span className="mut" style={{ fontSize: 'var(--fs-sub)' }}>
            共 {data?.total} 项能力，来自 skills/ 与对话能力，分组定义见 capabilities.toml
          </span>
        </div>
      ) : null}
    </div>
  )
}

export default CapabilityPage
