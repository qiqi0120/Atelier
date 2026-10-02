import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Calendar as CalendarIcon,
  ChartLine,
  FileText,
  Flame,
  Image as ImageIcon,
  KeyRound,
  Lightbulb,
  MonitorPlay,
  Music,
  PenLine,
  Search,
  Shield,
  SlidersHorizontal,
  Stethoscope,
  Code,
  Users,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Badge, Button, Chip, Drawer, Field, Input, Modal, toast } from '@/components'
import { MATURITY_LABEL } from '@/lib/types'
import type { Maturity, SkillLayer } from '@/lib/types'
import { PageHead } from '@/features/shared/PageHead'

type Skill = {
  id: string
  n: string
  layer: SkillLayer
  m: Maturity
  cost: string
  i: LucideIcon
  d: string
  body: string
  p?: { k: string; v: string }[]
  needKey?: string
  keyLabel?: string
}

const SKILLS: Skill[] = [
  {
    id: 'xhs-card',
    n: '小红书知识卡',
    layer: '制作',
    m: 'v0',
    cost: '本地 · 免费',
    i: ImageIcon,
    p: [
      { k: '标题', v: 'AI 工具越用越笨' },
      { k: '张数', v: '3' },
      { k: '尺寸', v: '1080×1440' },
    ],
    d: '按平台竖版比例生成卡片组，输出到项目「成品」区。',
    body: `# 小红书知识卡

把一段内容拆成 **3–9 张竖版卡片**，每张一个论点。

## 硬门禁
- 尺寸 1080×1440（3:4），单张 ≤ 300KB
- 文字最小 32px，行距 1.5
- 极限词扫描 BLOCK 级

## 软提醒
- 「震惊 / 必看 / 绝了」等 AI 味词只告警
- 视觉质检：边缘密度、死白率、整体密度三项

\`\`\`yaml
output: outputs/<项目>/成品/card-01.png
gate: [size, wordcount, extreme_words, visual_density]
\`\`\``,
  },
  {
    id: 'de-ai',
    n: '去 AI 感改写',
    layer: '制作',
    m: 'v0',
    cost: '本地 · 免费',
    i: PenLine,
    p: [
      { k: '原文', v: '（粘贴或引用）' },
      { k: '风格', v: '随手记' },
    ],
    d: '砍填充语、打破公式化结构、主动语态、变化节奏。',
    body: `# 去 AI 感改写

目标不是「换同义词」，是 **拆掉 AI 的节奏**。

## 五维打分（改前 → 改后）
| 维度 | 说明 |
|---|---|
| 直接性 | 删掉铺垫段，直接给结论 |
| 节奏 | 长短句交替，避免三段等长 |
| 信任度 | 具体数字、时间、亲身细节 |
| 活人感 | 允许不完整的句子 |
| 精炼度 | 每段只留一个信息点 |

## 常见填充语黑名单
「首先 / 其次 / 值得注意的是」「在当今快节奏的时代」「总而言之」`,
  },
  {
    id: 't2s',
    n: '语音识别转字幕',
    layer: '制作',
    m: 'v0',
    cost: '本地模型',
    i: MonitorPlay,
    p: [
      { k: '音频', v: '（拖入）' },
      { k: '格式', v: 'SRT' },
    ],
    d: '音频/视频转 SRT/ASS/TXT/JSON，本地模型不上传。',
    body: `# 语音识别转字幕

本地 faster-whisper 推理，**默认不上传音频**。

## 输出
- \`SRT\` / \`ASS\`（可烧录样式）/ \`TXT\` / \`JSON\`（含分句时间戳）

## 门禁
- 时间轴单调不回退（硬）
- 静音段 < 0.4s 合并（软）`,
  },
  {
    id: 'one-video',
    n: '一键成片',
    layer: '制作',
    m: 'v2',
    cost: '按量计费 · 需密钥',
    i: MonitorPlay,
    needKey: 'MINIMAX_API_KEY',
    keyLabel: 'MiniMax API Key',
    d: '主题 → 文案 → 配图/AI 视频 → 配音 → 字幕 → BGM → 合成。',
    body: `# 一键成片

**付费操作**：调用 AI 生视频前先给费用预估，确认后才执行。

## 流水线
1. 文案（复用母版内容）
2. 分镜脚本（3–8 个镜头）
3. 画面：AI 生图 或 AI 生视频（可切换）
4. 配音：TTS 云端优先，edge 兜底
5. 字幕：识别 + 烧录
6. BGM：自动闪避混音
7. 合成：9:16 / 16:9

## 确认点
> 生视频 ¥1.2 / 段 × 5 段 ≈ ¥6.0，生图 ¥0.1 / 张 × 12 张 ≈ ¥1.2，配音 ¥0.4。总计 ≈ ¥7.6。

点「确认」才执行。`,
  },
  {
    id: 'aigc-img',
    n: 'AI 生图',
    layer: '制作',
    m: 'v2',
    cost: '按量计费 · 需密钥',
    i: ImageIcon,
    needKey: 'MINIMAX_API_KEY',
    keyLabel: 'MiniMax API Key',
    d: '文生图 / 图生图 / 变体，输出到成品区。',
    body: `# AI 生图

- 文生图、图生图、局部重绘、风格变体
- 默认 2:3 竖版 1080×1620

**费用规则**：执行前展示预估（张数 × 单价），用户确认后扣费。`,
  },
  {
    id: 'music',
    n: 'AI 音乐',
    layer: '制作',
    m: 'v3',
    cost: '按量计费 · 接入中',
    i: Music,
    needKey: 'MUSIC_API_KEY',
    keyLabel: '音乐 Provider Key',
    d: '生成原创 BGM，接入中（P3）。',
    body: `# AI 音乐（接入中）

当前未接入 provider。配置密钥后可用。

> 未配置不会影响其他功能——能力地图会把它标成「接入中」而不是报错。`,
  },
  {
    id: 'hot',
    n: '多平台热榜聚合',
    layer: '发现',
    m: 'v0',
    cost: '免费 · 缓存 10min',
    i: Flame,
    p: [
      { k: '平台', v: '全选' },
      { k: '条数', v: '50' },
    ],
    d: '抖音/微博/B站/小红书/知乎/头条/百度 7 源。',
    body: `# 多平台热榜聚合

7 源并发拉取，**8s 内返回或显示明确加载态**。

## 缓存
- TTL 10 分钟，切 tab 不重复拉取
- 抓取失败回落上次快照，并在 UI 上标注「12s 前」

## 深度加载
抖音增量翻页：40–70s / 约 120 次请求 / 有风控风险，必须显式提示代价。`,
  },
  {
    id: 'viral',
    n: '爆款拆解',
    layer: '策划',
    m: 'v0',
    cost: 'LLM · 约 ¥0.05',
    i: Search,
    p: [{ k: '对标内容', v: '（粘贴链接或正文）' }],
    d: '6 段式拆解：概括/钩子/结构/为何火/可复制模板/结合画像出选题。',
    body: `# 爆款拆解

固定 6 段输出，**第 6 段必须结合当前画像**给具体选题。

1. 一句话概括
2. 前 3 秒钩子拆解
3. 结构骨架（分点方式）
4. 为什么火（情绪 / 实用 / 身份认同）
5. 可复制模板（填空式）
6. 结合你的「AI 效率观察」画像，给 3 个可做选题`,
  },
  {
    id: 'score',
    n: '选题评分',
    layer: '策划',
    m: 'v1',
    cost: 'LLM · 约 ¥0.03',
    i: ChartLine,
    d: '流量/匹配/差异/时效/变现/成本/风险 7 维打分。',
    body: `# 选题评分

7 维加权 → 总分 + 结论（做 / 不做 / 改方向）。

- 硬伤项（同质化、违禁）直接给「不做」
- 单维分低但总分高 → 给「改方向」和具体改法`,
  },
  {
    id: 'cal',
    n: '内容日历排期',
    layer: '策划',
    m: 'v0',
    cost: '本地 · 免费',
    i: CalendarIcon,
    d: '选题排入月视图，平台活动占位提醒。',
    body: `# 内容日历排期

- 状态流转：选题 → 草稿 → 待发 → 已发
- 平台活动：只读占位条（斜纹样式），不可被内容覆盖
- 提前 N 天提醒（N 默认 3 天）`,
  },
  {
    id: 'gate',
    n: '发布前预检',
    layer: '发布',
    m: 'v0',
    cost: '本地 · 免费',
    i: Shield,
    d: '极限词/医疗功效硬门禁 + 标题打分 + 人设一致性软提醒。',
    body: `# 发布前预检

## 硬门禁（阻断）
- 各平台字数上限，超限标红且禁止发布
- 极限词、医疗功效、违禁品（BLOCK 级 fail-closed）
- 出站内容密钥扫描（发现密钥直接拒绝发布）

## 软提醒（不阻断）
- AI 味重、人设不符、标题偏弱
- 只告警并给改法，不替用户做决定`,
  },
  {
    id: 'xhs-pub',
    n: '小红书发布',
    layer: '发布',
    m: 'v0',
    cost: '浏览器自动化',
    i: ImageIcon,
    needKey: 'XHS_COOKIE',
    keyLabel: 'Cookie（可选，扫码可免）',
    d: '图文 + 视频，风控风险高，默认人工确认。',
    body: `# 小红书发布

- 需登录态真校验通过
- 风控风险高：平台可能检测自动化
- **默认保留「发布前人工确认」**，不建议无人值守定时发布
- 失败必须给明确原因（哪个字段没过 / 哪个接口报错）`,
  },
  {
    id: 'dy-pub',
    n: '抖音发布',
    layer: '发布',
    m: 'v0',
    cost: '浏览器自动化',
    i: MonitorPlay,
    d: '仅视频；风控时弹短信验证码弹窗（等待 5 分钟）。',
    body: `# 抖音发布

- 仅支持视频（图文会被平台拒）
- 短信墙：弹窗提示，等待 5 分钟，超时明确报错
- 错误码映射到人话，例如 \`dy_auth_4012\` → 「登录态过期，需重新扫码 + 短信验证码」`,
  },
  {
    id: 'gzh-pub',
    n: '公众号发布',
    layer: '发布',
    m: 'v0',
    cost: '官方 API',
    i: FileText,
    needKey: 'GZH_APPID / GZH_APPSECRET',
    keyLabel: 'AppID + AppSecret',
    d: '凭证登录，Markdown → 不掉样式的 HTML，需封面图。',
    body: `# 公众号发布

- 凭证登录：AppID / AppSecret（只写不回传）
- 排版：Markdown → 内联样式 HTML，粘贴到后台不掉样
- 必须有封面图，缺封面在预检里阻断`,
  },
  {
    id: 'analytics',
    n: '账号数据回收',
    layer: '归因',
    m: 'v0',
    cost: '浏览器自动化',
    i: ChartLine,
    d: '粉丝/获赞/作品数 + 与昨日上周上月去年同期对比。',
    body: `# 账号数据回收

- 定时 + 手动
- **失败时保留上次快照，不清空已有数据**
- 快照带时间戳，UI 显示「12:04 快照」`,
  },
  {
    id: 'retro',
    n: '内容复盘沉淀',
    layer: '归因',
    m: 'v0',
    cost: 'LLM · 约 ¥0.02',
    i: Lightbulb,
    d: '有效结构与偏好沉淀回画像（长期记忆）。',
    body: `# 内容复盘沉淀

- 从已发内容提取「结构规律」和「你的偏好」
- 写成**候选记忆**给用户确认，不直接改画像
- 用户点「采纳」才写入长期记忆`,
  },
  {
    id: 'comment',
    n: '评论洞察',
    layer: '归因',
    m: 'v1',
    cost: '浏览器自动化',
    i: Users,
    d: '拉取评论，提取高频反馈，可一键存为选题。',
    body: `# 评论洞察

- 按「求模板 / 质疑 / 追问 / 情绪」聚类
- 高频诉求可直接转选题入库`,
  },
  {
    id: 'doctor',
    n: '环境体检 doctor',
    layer: '通用',
    m: 'v0',
    cost: '本地 · 免费',
    i: Stethoscope,
    d: '15+ 项检查，覆盖 Python/Node/FFmpeg/Chromium/密钥/网络。',
    body: `# 环境体检 doctor

## 检查项（节选）
- Python ≥ 3.10
- Node ≥ 22
- FFmpeg
- Chromium
- 各通道密钥连通性
- 磁盘可写空间

## 原则
**失败要留痕**：每一项给明确原因，不返回「500」。一键安装可重复运行，失败即停。`,
  },
  {
    id: 'chat',
    n: '对话（流式）',
    layer: '通用',
    m: 'v0',
    cost: 'LLM · 按量',
    i: Code,
    needKey: 'LLM_API_KEY',
    keyLabel: '对话模型 Key',
    d: 'SSE 流式 + 独立思考流 + 随时中断 + 断线恢复。',
    body: `# 对话（流式）

- SSE 标准推送，**不用 tail 文件**
- 思考过程走独立流，可折叠
- 中断 ≤ 2s 生效
- 断线重连后从服务端取回该轮完整结果（每轮落盘）`,
  },
  {
    id: 'cron',
    n: '定时发布',
    layer: '发布',
    m: 'v3',
    cost: '本地调度',
    i: CalendarIcon,
    d: '排期到点自动发布（P2，建议与人工确认冲突时禁用）。',
    body: `# 定时发布（后期）

风险：无人值守发布在小红书/抖音容易触发风控。

**当前策略**：接入中。开启时若「发布前人工确认」为开，会在到点时提醒而不是直接发。`,
  },
]

const LAYERS: SkillLayer[] = ['发现', '策划', '制作', '发布', '归因', '通用']

export function SkillsPage() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [layer, setLayer] = useState('all')
  const [openId, setOpenId] = useState<string | null>(null)
  const [costConfirm, setCostConfirm] = useState(false)

  const list = useMemo(() => {
    const kw = q.trim().toLowerCase()
    return SKILLS.filter((s) => {
      if (layer !== 'all' && s.layer !== layer) return false
      if (kw && !(`${s.n}${s.d}`.toLowerCase().includes(kw))) return false
      return true
    })
  }, [q, layer])

  const open = SKILLS.find((s) => s.id === openId) ?? null
  const locked = Boolean(open?.needKey && open?.m !== 'v0')

  const run = () => {
    if (!open) return
    setOpenId(null)
    setCostConfirm(false)
    toast(`已提交：${open.n} → outputs/${open.id}/`, 'ok')
  }

  return (
    <div className="view-pad">
      <PageHead
        title="技能库"
        desc={
          <>
            进阶入口：单个技能的完整说明、就地运行、密钥配置。带{' '}
            <Badge tone="warn" style={{ verticalAlign: '1px' }}>
              !
            </Badge>{' '}
            的表示缺配置。
          </>
        }
        actions={
          <>
            <Input
              sizeSm
              placeholder="搜索技能 / 描述…"
              value={q}
              style={{ width: 190 }}
              onChange={(e) => setQ(e.target.value)}
              aria-label="搜索技能"
            />
            <Button icon={SlidersHorizontal} onClick={() => navigate('/settings')}>
              批量配置密钥
            </Button>
          </>
        }
      />

      <div className="tabs" style={{ marginBottom: 18 }}>
        <button type="button" className={`tab ${layer === 'all' ? 'on' : ''}`} onClick={() => setLayer('all')}>
          全部 <span className="mut2">{SKILLS.length}</span>
        </button>
        {LAYERS.map((l) => (
          <button type="button" key={l} className={`tab ${layer === l ? 'on' : ''}`} onClick={() => setLayer(l)}>
            {l}
          </button>
        ))}
      </div>

      {LAYERS.filter((l) => list.some((s) => s.layer === l)).map((l) => {
        const items = list.filter((s) => s.layer === l)
        return (
          <div className="cap-grp" key={l}>
            <div className="cap-grp-h">
              <h3>{l}层技能</h3>
              <span className="mut" style={{ fontSize: 'var(--fs-sub)' }}>
                {items.length} 个
              </span>
              <div className="sp">
                <Chip tone="outline">{items.filter((s) => s.m === 'v0').length} 个已验证</Chip>
              </div>
            </div>
            <div className="sk-grid">
              {items.map((s) => {
                const isLocked = Boolean(s.needKey && s.m !== 'v0')
                return (
                  <div className={`sk ${isLocked ? 'locked' : ''}`} key={s.id}>
                    {isLocked ? (
                      <>
                        <span className="warnbadge">!</span>
                        <span className="tool-tip">
                          缺 {s.needKey?.split(' / ')[0]}，运行已禁用
                        </span>
                      </>
                    ) : null}
                    <div className="top">
                      <span
                        className="ci"
                        style={{
                          width: 26,
                          height: 26,
                          borderRadius: 8,
                          background: 'var(--surface-2)',
                          color: 'var(--ink-2)',
                          display: 'grid',
                          placeItems: 'center',
                        }}
                      >
                        <s.i size={14} strokeWidth={1.9} />
                      </span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <h4>{s.n}</h4>
                        <span className={`mature ${s.m}`} style={{ marginTop: 3, display: 'inline-block' }}>
                          {MATURITY_LABEL[s.m]}
                        </span>
                      </div>
                    </div>
                    <p>{s.d}</p>
                    <div className="foot">
                      <Chip tone="outline" mono xs>
                        {s.cost}
                      </Chip>
                      <Button size="sm" style={{ marginLeft: 'auto' }} onClick={() => setOpenId(s.id)}>
                        详情 / 运行
                      </Button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}

      {list.length === 0 ? (
        <div className="card card-b">
          <p className="mut" style={{ fontSize: 'var(--fs-sub)' }}>
            没有匹配的技能，试试搜「字幕」「发布」或切到别的层。
          </p>
        </div>
      ) : null}

      <div className="card card-b" style={{ marginTop: 6, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="mut" style={{ fontSize: 'var(--fs-sub)' }}>
          MVP 核心技能 40 个已建 {SKILLS.length} 个（原型只展示代表性子集）
        </span>
        <Chip tone="outline" mono className="sp" style={{ marginLeft: 'auto' }}>
          skills/ · 每个技能一个 SKILL.md
        </Chip>
      </div>

      <Drawer
        open={Boolean(open)}
        onClose={() => setOpenId(null)}
        title={open?.n ?? ''}
        meta={
          open ? (
            <>
              <span className={`mature ${open.m}`}>{MATURITY_LABEL[open.m]}</span>
              <Chip tone="outline" mono>
                skill/{open.id}
              </Chip>
              <Chip tone="outline">{open.layer}层</Chip>
              <Chip tone="outline" mono>
                {open.cost}
              </Chip>
            </>
          ) : null
        }
        footer={
          open ? (
            <>
              <span className="help" style={{ flex: 1 }}>
                就地运行会写入 <code className="mono">outputs/&lt;项目&gt;/</code>
              </span>
              <Button onClick={() => setOpenId(null)}>取消</Button>
              <Button
                variant="primary"
                disabled={locked}
                disabledReason={locked ? `缺 ${open.needKey?.split(' / ')[0]}` : undefined}
                onClick={() => {
                  if (open.cost.includes('计费')) setCostConfirm(true)
                  else run()
                }}
              >
                {locked ? '缺密钥，已禁用' : '运行'}
              </Button>
            </>
          ) : null
        }
      >
        {open ? (
          <>
            <div className="md">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{open.body}</ReactMarkdown>
            </div>
            {open.p?.length ? (
              <>
                <div className="hr" />
                <div className="lbl" style={{ marginBottom: 9 }}>
                  运行参数
                </div>
                {open.p.map((p) => (
                  <Field label={p.k} key={p.k}>
                    {(id) => <Input id={id} defaultValue={p.v} />}
                  </Field>
                ))}
              </>
            ) : null}
            {open.needKey ? (
              <>
                <div className="hr" />
                <div className="lbl" style={{ marginBottom: 9 }}>
                  API 配置
                </div>
                <Field
                  label={open.keyLabel ?? open.needKey}
                  help={
                    locked ? (
                      <b style={{ color: 'var(--warn-ink)' }}>当前未配置</b>
                    ) : (
                      <>
                        已配置（末尾 <span className="mono">••••3f7a</span>）。留空保存不会覆盖已存值。
                      </>
                    )
                  }
                >
                  {(id) => (
                    <Input
                      id={id}
                      mono
                      revealable
                      placeholder={locked ? '未配置 · 填写后可运行' : '已配置 · 留空不覆盖'}
                    />
                  )}
                </Field>
                <Field label="Base URL（可选）">
                  {(id) => <Input id={id} mono defaultValue="https://api.minimaxi.com/v1" />}
                </Field>
              </>
            ) : null}
            <div className="hr" />
            <div className="lbl" style={{ marginBottom: 9 }}>
              产物落盘位置
            </div>
            <div className="path">outputs/{open.id}/</div>
            <div className="help" style={{ marginTop: 7 }}>
              路径解析统一由 <span className="mono">paths.py</span> 收口，业务代码不自己拼路径。
            </div>
          </>
        ) : null}
      </Drawer>

      <Modal
        open={costConfirm}
        onClose={() => setCostConfirm(false)}
        title={`运行「${open?.n}」会产生费用`}
        sub="付费操作：先看清楚预估，确认后才执行。"
        okText="我知道代价，继续"
        onOk={run}
      >
        <div className="precheck">
          <div className="s w">
            <KeyRound size={10} />
          </div>
          <div>
            <b>约 ¥7.6</b>
            <span>生视频 ¥1.2 × 5 段 · 生图 ¥0.1 × 12 张 · 配音 ¥0.4</span>
          </div>
        </div>
        <div className="precheck">
          <div className="s d">
            <Shield size={10} />
          </div>
          <div>
            <b>缺密钥则无法运行</b>
            <span>缺 {open?.needKey}，请先在设置页配置。</span>
          </div>
        </div>
      </Modal>
    </div>
  )
}

export default SkillsPage
