/** SPEC-08 §6 · F-E8 爆款拆解弹层：粘贴原文 → 6 段式拆解 → 一键存入选题库。 */

import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button, Chip, Field, Input, Modal, Select, Textarea, toast } from '@/components'
import { useAtelier } from '@/lib/store'
import { topicsApi } from './api'
import { describeError } from './describe'
import type { DecodeResult } from './types'

const PLATFORM_OPTIONS = [
  { value: '', label: '不限平台' },
  { value: 'xhs', label: '小红书' },
  { value: 'dy', label: '抖音' },
  { value: 'gzh', label: '公众号' },
]

export type DecodeDialogProps = {
  open: boolean
  onClose: () => void
  /** 存入选题库成功后回调（父层刷新列表） */
  onSaved: () => void
}

export function DecodeDialog({ open, onClose, onSaved }: DecodeDialogProps) {
  const { profile } = useAtelier()
  const profileId = profile && !profile.generalMode ? profile.id : undefined

  const [text, setText] = useState('')
  const [metrics, setMetrics] = useState('')
  const [platform, setPlatform] = useState('')
  const [goal, setGoal] = useState('')
  const [running, setRunning] = useState(false)
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<DecodeResult | null>(null)
  const [errorText, setErrorText] = useState('')

  const reset = () => {
    setResult(null)
    setErrorText('')
  }

  const close = () => {
    reset()
    setText('')
    setMetrics('')
    setPlatform('')
    setGoal('')
    onClose()
  }

  const tooShort = text.trim().length < 40

  const run = async () => {
    setRunning(true)
    setErrorText('')
    try {
      setResult(
        await topicsApi.decode({ text, metrics, platform, goal, profile_id: profileId }),
      )
    } catch (e) {
      setErrorText(describeError(e))
    } finally {
      setRunning(false)
    }
  }

  const save = async () => {
    if (!result) return
    setSaving(true)
    setErrorText('')
    try {
      await topicsApi.create({
        title: result.topic_seed.title || '拆解选题',
        source: 'decode',
        source_ref: result.topic_seed.title,
        decode: result.decode_markdown,
        profile_id: profileId,
      })
      toast.ok('已存入选题库（待做列）')
      onSaved()
      close()
    } catch (e) {
      setErrorText(describeError(e))
    } finally {
      setSaving(false)
    }
  }

  const warnings = (result?.gate_report.items ?? []).filter(
    (i) => !i.passed && i.severity === 'warn',
  )

  return (
    <Modal
      open={open}
      onClose={close}
      title="爆款拆解"
      sub="粘贴对标内容，只拆结构不抄内容，出 6 段式拆解"
      width={680}
      footer={
        result ? (
          <>
            <Button onClick={() => setResult(null)}>重新拆解</Button>
            <Button variant="primary" loading={saving} onClick={() => void save()}>
              存入选题库
            </Button>
          </>
        ) : (
          <>
            <Button onClick={close}>取消</Button>
            <Button
              variant="primary"
              disabled={tooShort || running}
              loading={running}
              onClick={() => void run()}
            >
              开始拆解
            </Button>
          </>
        )
      }
    >
      {result ? (
        <div className="stack" style={{ gap: 12 }}>
          <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
            <Chip tone="accent">拆解完成</Chip>
            {warnings.map((w, i) => (
              <Chip key={i} tone="warn" title={w.message}>
                软提醒 ×{warnings.length}
              </Chip>
            ))}
          </div>
          {warnings.length ? (
            <div style={{ fontSize: 12, color: 'var(--warn)', lineHeight: 1.55 }}>
              {warnings.map((w, i) => (
                <div key={i}>
                  {w.message}
                  {w.fix_hint ? `（${w.fix_hint}）` : ''}
                </div>
              ))}
            </div>
          ) : null}
          <div className="md" data-testid="decode-md">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.decode_markdown}</ReactMarkdown>
          </div>
        </div>
      ) : (
        <div className="stack" style={{ gap: 12 }}>
          <Field
            label="对标原文"
            required
            help={tooShort ? `至少 40 字（当前 ${text.trim().length} 字），太短拆不动` : '完整文案或整理出来的截图文字'}
          >
            {(id) => (
              <Textarea
                id={id}
                rows={7}
                placeholder="把爆款原文贴进来……"
                value={text}
                onChange={(e) => setText(e.target.value)}
              />
            )}
          </Field>
          <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 200 }}>
              <Field label="数据表现" help="如：赞 3.2w 藏 1.1w 评 876，没有可留空">
                {(id) => <Input id={id} value={metrics} onChange={(e) => setMetrics(e.target.value)} />}
              </Field>
            </div>
            <div style={{ width: 150, flex: 'none' }}>
              <Field label="平台">
                {(id) => (
                  <Select id={id} options={PLATFORM_OPTIONS} value={platform} onChange={(e) => setPlatform(e.target.value)} />
                )}
              </Field>
            </div>
          </div>
          <Field label="我的目标" help="如：涨粉 / 带货 / 引流私域，选题会朝目标倾斜">
            {(id) => <Input id={id} value={goal} onChange={(e) => setGoal(e.target.value)} />}
          </Field>
        </div>
      )}
      {errorText ? (
        <p className="sysfile danger" style={{ whiteSpace: 'pre-line' }} role="alert">
          {errorText}
        </p>
      ) : null}
    </Modal>
  )
}

export default DecodeDialog
