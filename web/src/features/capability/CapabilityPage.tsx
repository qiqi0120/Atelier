import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  BarChart3,
  Calendar as CalendarIcon,
  Check,
  Code,
  FileText,
  Flame,
  Image as ImageIcon,
  Key,
  Lightbulb,
  MonitorPlay,
  PenLine,
  Search,
  Shield,
  Sparkles,
  Stethoscope,
  Target,
  Users,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Chip, Input, Tabs, toast } from '@/components'
import { MATURITY_LABEL } from '@/lib/types'
import type { Maturity } from '@/lib/types'
import { useAtelier } from '@/lib/store'
import { PageHead } from '@/features/shared/PageHead'

type Cap = { i: LucideIcon; n: string; t: string; m: Maturity }
type Group = { g: string; d: string; items: Cap[] }

const CAPS: Group[] = [
  {
    g: '做内容 · 要成品',
    d: '给一句主题，产出能直接发的东西',
    items: [
      { i: ImageIcon, n: '小红书知识卡', t: '当你说「做成小红书图文」「知识卡」时使用', m: 'v0' },
      { i: PenLine, n: '通用社媒文案', t: '当你说「写条小红书/微博/知乎文案」时使用', m: 'v0' },
      { i: Sparkles, n: '去 AI 感改写', t: '当你说「太 AI 了」「改得自然点」时使用', m: 'v0' },
      { i: ImageIcon, n: 'AI 生图 / 图生图', t: '当你说「配图」「画一张」时使用', m: 'v2' },
      { i: FileText, n: '公众号排版', t: '当你说「排版成公众号 HTML」时使用', m: 'v0' },
      { i: MonitorPlay, n: '一键成片', t: '当你说「做成视频」「竖版成片」时使用', m: 'v2' },
      { i: BarChart3, n: '图表可视化', t: '当你说「把这段数据做成图」时使用', m: 'v1' },
    ],
  },
  {
    g: '做运营 · 要动作',
    d: '把「今天发什么」变成明确的下一步',
    items: [
      { i: Flame, n: '今日热榜聚合', t: '当你说「今天有什么热点」时使用', m: 'v0' },
      { i: Search, n: '爆款拆解', t: '当你说「拆解这条爆款」时使用', m: 'v0' },
      { i: Target, n: '选题评分', t: '当你说「这个选题值得做吗」时使用', m: 'v1' },
      { i: CalendarIcon, n: '排入内容日历', t: '当你说「排到周三晚上发」时使用', m: 'v0' },
      { i: Shield, n: '发布前预检', t: '当你说「检查一下能不能发」时使用', m: 'v0' },
    ],
  },
  {
    g: '做账号 · 要增长',
    d: '用真实数据反过来改内容',
    items: [
      { i: BarChart3, n: '账号数据 / 增长对比', t: '当你说「这周涨了多少粉」时使用', m: 'v0' },
      { i: Users, n: '评论洞察', t: '当你说「评论区都在问什么」时使用', m: 'v1' },
      { i: Lightbulb, n: '内容复盘沉淀', t: '当你说「这次为什么爆」时使用', m: 'v0' },
      { i: Search, n: '竞品选题拆解', t: '当你说「对标账号在发什么」时使用', m: 'v2' },
    ],
  },
  {
    g: '做系统 · 要配置',
    d: '工具坏了、缺密钥、想体检时用',
    items: [
      { i: Key, n: '账号登录 / 登录态校验', t: '当你说「小红书掉登录了」时使用', m: 'v0' },
      { i: Stethoscope, n: '环境体检 doctor', t: '当你说「环境有问题」时使用', m: 'v0' },
      { i: Code, n: '模型通道自检', t: '当你说「模型连不上」时使用', m: 'v0' },
      { i: Code, n: 'CLI 技能直跑', t: '当你说「用命令行跑这个技能」时使用', m: 'v1' },
    ],
  },
]

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

  const groups = useMemo(() => {
    const kw = q.trim().toLowerCase()
    return CAPS.map((g) => ({
      ...g,
      items: g.items.filter((c) => {
        if (kw && !(`${c.n}${c.t}`.toLowerCase().includes(kw))) return false
        if (filter === 'ready') return c.m === 'v0' || c.m === 'v1'
        if (filter === 'needcfg') return c.m === 'v2' || c.m === 'v3'
        return true
      }),
    })).filter((g) => g.items.length > 0)
  }, [q, filter])

  // 交互规则 1：点卡片只填入输入框，绝不自动发送（F-C4）
  const fill = (name: string) => {
    fillPrompt(`帮我做「${name}」`)
    navigate('/chat')
    toast('已填入输入框，确认后点发送', 'ok')
  }

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

      {groups.length === 0 ? (
        <div className="card card-b">
          <p className="mut" style={{ fontSize: 'var(--fs-sub)' }}>
            没有匹配「{q}」的能力，换个说法或清空搜索。
          </p>
        </div>
      ) : null}

      {groups.map((g) => (
        <div className="cap-grp" key={g.g}>
          <div className="cap-grp-h">
            <h3>{g.g}</h3>
            <span className="mut" style={{ fontSize: 'var(--fs-sub)' }}>
              {g.d}
            </span>
            <div className="sp">
              <Chip tone="outline">{g.items.length} 项能力</Chip>
            </div>
          </div>
          <div className="cap-items">
            {g.items.map((c) => (
              <button type="button" className="cap" key={c.n} onClick={() => fill(c.n)}>
                <div className="top">
                  <span className="ci">
                    <c.i size={14} strokeWidth={1.9} />
                  </span>
                  <h4>{c.n}</h4>
                </div>
                <div className="trig">{c.t}</div>
                <div className="foot">
                  <span className={`mature ${c.m}`}>{MATURITY_LABEL[c.m]}</span>
                  <span className="go">
                    填入输入框
                    <Check size={11} />
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export default CapabilityPage
