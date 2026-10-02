import { useNavigate } from 'react-router-dom'
import {
  ArrowRight,
  ArrowUp,
  BarChart3,
  Check,
  Clock,
  Flame,
  Image as ImageIcon,
  MonitorPlay,
  User,
} from 'lucide-react'
import { Button, Card, Chip, toast } from '@/components'
import { useAtelier } from '@/lib/store'

type Feed = [string, string, string, string]

/** 今日热榜速览（与原型同款占位数据，M2 接 /api/hot 后替换） */
const FEED: Feed[] = [
  ['AI 工具越用越笨', '1.2w', '+312%', '抖音'],
  ['第一批 90 后开始整顿职场', '9820', '+180%', '抖音'],
  ['iPhone 18 影像提前泄露', '8760', '+92%', '抖音'],
  ['普通人怎么用 Agent 省钱', '6540', '+76%', '抖音'],
  ['小红书「反内卷」新规', '4.1w', '+240%', '微博'],
  ['大学生开始「付费上班」', '2.7w', '+160%', '微博'],
]

function greet(): string {
  const h = new Date().getHours()
  const word = h < 6 ? '深夜好' : h < 11 ? '早上好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好'
  return `${word}，Mr Yu`
}

export function WorkbenchPage() {
  const navigate = useNavigate()
  const fillPrompt = useAtelier((s) => s.fillPrompt)

  const ask = (text: string) => {
    fillPrompt(text)
    navigate('/chat')
    toast('已填入输入框，确认后点发送', 'ok')
  }

  return (
    <div className="view-pad stack" style={{ gap: 18 }}>
      <div className="hero">
        <div>
          <div className="row" style={{ gap: 7 }}>
            <h2>{greet()}</h2>
            <Chip tone="accent" icon={<i className="live-dot" />}>
              画像已生效
            </Chip>
          </div>
          <p>
            今天有 <b style={{ color: 'var(--ink)' }}>3 条</b> 待发内容 · 2 个选题卡在「进行中」 · 抖音号登录态将在{' '}
            <b style={{ color: 'var(--ink)' }}>6 小时后</b>过期
          </p>
        </div>
        <div className="hero-r">
          <Button onClick={() => navigate('/calendar')}>看排期</Button>
          <Button variant="primary" onClick={() => ask('帮我把母版标题改得更适合小红书和抖音')}>
            让 AI 帮我写今天的稿
          </Button>
        </div>
      </div>

      <div className="stat-row">
        <Card>
          <div className="kpi">
            <b>
              12.4<span className="unit">k</span>
            </b>
            <span>本周涨粉</span>
            <span className="delta up">↑ 18% 环比</span>
          </div>
        </Card>
        <Card>
          <div className="kpi">
            <b>3</b>
            <span>待发内容</span>
            <span className="delta dn">↓ 1 已超期</span>
          </div>
        </Card>
        <Card>
          <div className="kpi">
            <b>2</b>
            <span>进行中选题</span>
            <span className="mut2" style={{ fontSize: 'var(--fs-help)' }}>
              共 12 条在库
            </span>
          </div>
        </Card>
        <Card>
          <div className="kpi">
            <b>
              86<span className="unit">%</span>
            </b>
            <span>门禁一次通过率</span>
            <span className="mut2" style={{ fontSize: 'var(--fs-help)' }}>
              本周 21 次产出
            </span>
          </div>
        </Card>
      </div>

      <div className="grid2" style={{ alignItems: 'start' }}>
        <Card
          title="今日待办"
          actions={<Chip tone="outline">3 项</Chip>}
          bodyStyle={{ padding: '4px 16px 8px' }}
        >
          <div className="task" onClick={() => navigate('/publish')}>
            <div className="ti">
              <Clock size={14} />
            </div>
            <div className="tx">
              <b>「AI 工具越用越笨」的 3 个真实原因</b>
              <span>排期 18:00 · 小红书 + 抖音</span>
            </div>
            <Chip tone="warn">待发</Chip>
          </div>
          <div className="task" onClick={() => navigate('/chat')}>
            <div className="ti">
              <ArrowUp size={14} />
            </div>
            <div className="tx">
              <b>补完选题「我用 3 个 Agent 砍掉一半内容流程」</b>
              <span>进行中 · 已写 60%</span>
            </div>
            <Chip tone="info">草稿</Chip>
          </div>
          <div className="task" onClick={() => navigate('/accounts')}>
            <div className="ti">
              <User size={14} />
            </div>
            <div className="tx">
              <b>重新验证抖音登录态</b>
              <span>6 小时后过期 · 需短信验证码</span>
            </div>
            <Chip tone="danger">阻塞</Chip>
          </div>
        </Card>

        <Card
          title="快捷入口"
          actions={
            <Button size="sm" variant="ghost" iconRight={ArrowRight} onClick={() => navigate('/capability')}>
              全部能力
            </Button>
          }
        >
          <div className="quick">
            <button type="button" onClick={() => ask('帮我做「小红书知识卡」')}>
              <div className="qi">
                <ImageIcon size={15} />
              </div>
              <div>
                <b>做成品</b>
                <span>小红书知识卡 · 1080×1440</span>
              </div>
            </button>
            <button type="button" onClick={() => ask('帮我做「一键成片」')}>
              <div className="qi">
                <MonitorPlay size={15} />
              </div>
              <div>
                <b>出视频</b>
                <span>一键成片 · 主题直接出竖版</span>
              </div>
            </button>
            <button type="button" onClick={() => navigate('/hot')}>
              <div className="qi">
                <Flame size={15} />
              </div>
              <div>
                <b>找选题</b>
                <span>今日热榜 7 源已更新</span>
              </div>
            </button>
            <button type="button" onClick={() => navigate('/analytics')}>
              <div className="qi">
                <BarChart3 size={15} />
              </div>
              <div>
                <b>看数据</b>
                <span>昨日 3 条表现回收完成</span>
              </div>
            </button>
          </div>
        </Card>
      </div>

      <div className="grid2" style={{ alignItems: 'start' }}>
        <Card
          title="今日热榜速览"
          actions={
            <>
              <Chip tone="outline">缓存命中 12s 前</Chip>
              <Button size="sm" variant="ghost" onClick={() => navigate('/hot')}>
                进入发现
              </Button>
            </>
          }
          bodyStyle={{ padding: '2px 16px 6px' }}
        >
          {FEED.map(([title, heat, delta, src], i) => (
            <div className="feed-item" key={title} onClick={() => ask(`帮我把「${title}」写成小红书图文，要 3 张知识卡的量`)}>
              <span className={`feed-rank ${i < 3 ? 'hot' : ''}`}>{i + 1}</span>
              <div className="feed-b">
                <b>{title}</b>
                <div className="feed-m">
                  <span className="spark">{heat}</span>
                  <span>{delta}</span>
                  <Chip tone="outline" xs>
                    {src}
                  </Chip>
                </div>
              </div>
              <Button
                size="sm"
                variant="ghost"
                style={{ opacity: 0 }}
                onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                onMouseLeave={(e) => (e.currentTarget.style.opacity = '0')}
                onClick={(e) => {
                  e.stopPropagation()
                  ask(`帮我把「${title}」写成小红书图文，要 3 张知识卡的量`)
                }}
              >
                做成内容
              </Button>
            </div>
          ))}
        </Card>

        <Card
          title="最近产出"
          actions={
            <Button size="sm" variant="ghost" onClick={() => navigate('/library')}>
              内容库
            </Button>
          }
        >
          <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 120 }}>
              <div className="mut2" style={{ fontSize: 11, marginBottom: 5 }}>
                图文
              </div>
              <div className="row" style={{ gap: 5, flexWrap: 'wrap' }}>
                <Chip tone="outline">去AI感改写</Chip>
                <Chip tone="outline">字数裁剪</Chip>
                <Chip tone="accent">门禁通过 2/2</Chip>
              </div>
            </div>
            <div style={{ flex: 1, minWidth: 120 }}>
              <div className="mut2" style={{ fontSize: 11, marginBottom: 5 }}>
                视频
              </div>
              <div className="row" style={{ gap: 5, flexWrap: 'wrap' }}>
                <Chip tone="outline">自动字幕</Chip>
                <Chip tone="outline">横转竖</Chip>
                <Chip tone="warn">画质待确认</Chip>
              </div>
            </div>
          </div>
          <div className="hr" />
          <div className="mut" style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 7 }}>
            <Check size={14} style={{ color: 'var(--accent)' }} />
            昨日 3 条内容数据已回收，2 条有效结构沉淀进画像
          </div>
        </Card>
      </div>
    </div>
  )
}

export default WorkbenchPage
