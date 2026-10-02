/** SPEC-08 · 选题库页（M2-1，占位页转正）。
 *
 * 布局：PageHead（搜索 + 拆解/矩阵/新建）+ 三列看板（待做/进行中/已完成）。
 * 卡片操作：评分（F-E9）· 钩子（F-E11）· 左右流转状态 · 删除（二次确认）。
 * 拆解（F-E8）与矩阵（F-E10）从顶部工具条进，生成结果落「待做」列。
 */

import { useMemo, useState } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  Flame,
  LayoutGrid,
  ListChecks,
  Plus,
  Tag,
  Trash2,
} from 'lucide-react'
import { Button, Card, Chip, ConfirmDialog, EmptyState, Input, Modal, Field, Textarea, toast } from '@/components'
import { PageHead } from '@/features/shared/PageHead'
import { useTopics } from './useTopics'
import { DecodeDialog } from './DecodeDialog'
import { MatrixDialog } from './MatrixDialog'
import { ScoreDialog } from './ScoreDialog'
import { HooksDialog } from './HooksDialog'
import { SOURCE_LABEL, STATUS_FLOW, STATUS_LABEL, type Topic, type TopicStatus } from './types'

export function TopicsPage() {
  const t = useTopics()
  const [createOpen, setCreateOpen] = useState(false)
  const [decodeOpen, setDecodeOpen] = useState(false)
  const [matrixOpen, setMatrixOpen] = useState(false)
  const [scoring, setScoring] = useState<Topic | null>(null)
  const [hooking, setHooking] = useState<Topic | null>(null)
  const [deleting, setDeleting] = useState<Topic | null>(null)

  const counts = useMemo(() => {
    const c: Record<TopicStatus, number> = { todo: 0, doing: 0, done: 0 }
    for (const it of t.items) c[it.status] += 1
    return c
  }, [t.items])

  const createTopic = async (title: string, angle: string) => {
    await t.create(title, angle)
    toast.ok('选题已加入「待做」列')
    setCreateOpen(false)
  }

  return (
    <div className="view-pad">
      <PageHead
        title="选题库"
        desc="写什么不再拍脑袋：拆爆款、矩阵出题、7 维评分，定了就排产。"
        actions={
          <>
            <Input
              sizeSm
              placeholder="搜标题 / 角度…"
              style={{ width: 160 }}
              aria-label="搜索选题"
              value={t.qDraft}
              onChange={(e) => t.setQDraft(e.target.value)}
            />
            <Button icon={Flame} onClick={() => setDecodeOpen(true)}>
              爆款拆解
            </Button>
            <Button icon={LayoutGrid} onClick={() => setMatrixOpen(true)}>
              内容矩阵
            </Button>
            <Button variant="primary" icon={Plus} onClick={() => setCreateOpen(true)}>
              新建选题
            </Button>
          </>
        }
      />

      {t.error ? (
        <p className="sysfile danger">
          {t.error} <button type="button" className="btn ghost sm" onClick={t.refresh}><span className="btn-txt">重试</span></button>
        </p>
      ) : null}

      {t.loading && t.items.length === 0 ? (
        <Card title="加载中…" tight>
          <div style={{ height: 120 }} />
        </Card>
      ) : t.items.length === 0 ? (
        <Card tight>
          <EmptyState
            icon={<ListChecks size={22} />}
            title="选题池还是空的"
            description="粘贴一条对标内容拆出选题，或者用内容矩阵一次生成一批。"
            actionLabel="先拆一条爆款试试"
            onAction={() => setDecodeOpen(true)}
          />
        </Card>
      ) : (
        <div className="topics-board" data-testid="topics-board">
          {STATUS_FLOW.map((status) => {
            const list = t.byStatus(status)
            return (
              <Card
                key={status}
                title={STATUS_LABEL[status]}
                actions={<Chip tone="outline">{counts[status]}</Chip>}
                tight
              >
                <div className="topic-col" data-testid={`col-${status}`}>
                  {list.length === 0 ? (
                    <p style={{ margin: 0, fontSize: 12.5, color: 'var(--muted)', padding: '4px 2px' }}>
                      {status === 'todo' ? '拆解或矩阵生成的选题会落在这里' : '暂无'}
                    </p>
                  ) : (
                    list.map((topic) => (
                      <TopicCard
                        key={topic.id}
                        topic={topic}
                        onScore={() => setScoring(topic)}
                        onHooks={() => setHooking(topic)}
                        onMove={(dir) => void t.move(topic, dir)}
                        onDelete={() => setDeleting(topic)}
                      />
                    ))
                  )}
                </div>
              </Card>
            )
          })}
        </div>
      )}

      <CreateTopicModal open={createOpen} onClose={() => setCreateOpen(false)} onCreate={createTopic} />
      <DecodeDialog open={decodeOpen} onClose={() => setDecodeOpen(false)} onSaved={t.refresh} />
      <MatrixDialog open={matrixOpen} onClose={() => setMatrixOpen(false)} onSaved={t.refresh} />
      <ScoreDialog open={scoring !== null} topic={scoring} onClose={() => setScoring(null)} />
      <HooksDialog open={hooking !== null} topic={hooking} onClose={() => setHooking(null)} />
      <ConfirmDialog
        open={deleting !== null}
        title="删除这条选题？"
        sub={deleting ? `「${deleting.title}」及其评分历史将一并删除，不可恢复。` : undefined}
        okText="删除选题"
        danger
        onCancel={() => setDeleting(null)}
        onConfirm={() => {
          if (deleting) void t.remove(deleting.id)
          setDeleting(null)
        }}
      />
    </div>
  )
}

function TopicCard(props: {
  topic: Topic
  onScore: () => void
  onHooks: () => void
  onMove: (dir: -1 | 1) => void
  onDelete: () => void
}) {
  const { topic } = props
  const i = STATUS_FLOW.indexOf(topic.status)
  return (
    <div className="topic-card" data-testid={`topic-${topic.id}`}>
      <span className="t">{topic.title}</span>
      {topic.angle ? <span className="angle">{topic.angle}</span> : null}
      <div className="foot">
        <Chip tone={topic.source === 'decode' ? 'info' : topic.source === 'matrix' ? 'neutral' : 'outline'}>
          {SOURCE_LABEL[topic.source]}
        </Chip>
        <div className="topic-acts">
          <button type="button" className="iconbtn" title="评分" aria-label={`评分：${topic.title}`} onClick={props.onScore}>
            <ListChecks size={15} />
          </button>
          <button type="button" className="iconbtn" title="标题钩子" aria-label={`钩子：${topic.title}`} onClick={props.onHooks}>
            <Tag size={15} />
          </button>
          {i > 0 ? (
            <button type="button" className="iconbtn" title="往回挪" aria-label={`回退：${topic.title}`} onClick={() => props.onMove(-1)}>
              <ArrowLeft size={15} />
            </button>
          ) : null}
          {i < STATUS_FLOW.length - 1 ? (
            <button type="button" className="iconbtn" title="往下推" aria-label={`推进：${topic.title}`} onClick={() => props.onMove(1)}>
              <ArrowRight size={15} />
            </button>
          ) : null}
          <button
            type="button"
            className="iconbtn danger"
            title="删除"
            aria-label={`删除：${topic.title}`}
            onClick={props.onDelete}
          >
            <Trash2 size={15} />
          </button>
        </div>
      </div>
    </div>
  )
}

function CreateTopicModal(props: {
  open: boolean
  onClose: () => void
  onCreate: (title: string, angle: string) => Promise<void>
}) {
  const [title, setTitle] = useState('')
  const [angle, setAngle] = useState('')
  const [saving, setSaving] = useState(false)

  const close = () => {
    setTitle('')
    setAngle('')
    props.onClose()
  }

  const submit = async () => {
    if (!title.trim() || saving) return
    setSaving(true)
    try {
      await props.onCreate(title.trim(), angle.trim())
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={props.open}
      onClose={close}
      title="新建选题"
      width={520}
      footer={
        <>
          <Button onClick={close}>取消</Button>
          <Button variant="primary" disabled={!title.trim()} loading={saving} onClick={() => void submit()}>
            创建
          </Button>
        </>
      }
    >
      <div className="stack" style={{ gap: 12 }}>
        <Field label="标题" required help="具体到能直接开工；最长 80 字">
          {(id) => (
            <Input
              id={id}
              placeholder="如：300 元拿下全身通勤穿搭"
              value={title}
              maxLength={80}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void submit()
              }}
            />
          )}
        </Field>
        <Field label="备注角度" help="切口、对标、想验证的假设（可选）">
          {(id) => (
            <Textarea
              id={id}
              rows={3}
              value={angle}
              maxLength={200}
              onChange={(e) => setAngle(e.target.value)}
            />
          )}
        </Field>
      </div>
    </Modal>
  )
}

export default TopicsPage
