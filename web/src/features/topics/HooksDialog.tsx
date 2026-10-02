/** SPEC-08 §6 · F-E11 标题 Hook 弹层：多变体 + 逐条字数校验，可一键设为标题。 */

import { useState } from 'react'
import { Check } from 'lucide-react'
import { Button, Chip, Field, Modal, Select, toast } from '@/components'
import { useAtelier } from '@/lib/store'
import { topicsApi } from './api'
import { describeError } from '@/lib/gates'
import type { HooksResult, Topic } from './types'

const PLATFORM_OPTIONS = [
  { value: '', label: '缺省（抖音标题 55 字，从严）' },
  { value: 'xhs', label: '小红书' },
  { value: 'dy', label: '抖音标题' },
  { value: 'gzh', label: '公众号' },
]

export type HooksDialogProps = {
  open: boolean
  topic: Topic | null
  onClose: () => void
}

export function HooksDialog({ open, topic, onClose }: HooksDialogProps) {
  const { profile } = useAtelier()
  const profileId = profile && !profile.generalMode ? profile.id : undefined

  const [platform, setPlatform] = useState('')
  const [variants, setVariants] = useState<HooksResult['variants']>([])
  const [running, setRunning] = useState(false)
  const [applying, setApplying] = useState<string | null>(null)
  const [errorText, setErrorText] = useState('')

  const close = () => {
    setVariants([])
    setErrorText('')
    setPlatform('')
    onClose()
  }

  const run = async () => {
    if (!topic) return
    setRunning(true)
    setErrorText('')
    try {
      const r = await topicsApi.hooks({ topic_id: topic.id, platform, profile_id: profileId })
      setVariants(r.variants)
    } catch (e) {
      setErrorText(describeError(e))
    } finally {
      setRunning(false)
    }
  }

  const apply = async (text: string) => {
    if (!topic) return
    setApplying(text)
    setErrorText('')
    try {
      await topicsApi.update(topic.id, { title: text })
      toast.ok('已设为选题标题')
      onClose()
    } catch (e) {
      setErrorText(describeError(e))
    } finally {
      setApplying(null)
    }
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="标题钩子"
      sub={topic ? `给「${topic.title}」生成多套开头钩子，逐条过字数校验` : undefined}
      width={600}
      footer={
        <>
          <Button onClick={close}>关闭</Button>
          <Button
            variant="primary"
            disabled={!topic || running}
            loading={running}
            onClick={() => void run()}
          >
            {variants.length ? '重新生成' : '生成变体'}
          </Button>
        </>
      }
    >
      {topic ? (
        <div className="stack" style={{ gap: 12 }}>
          <div style={{ width: 260 }}>
            <Field label="字数口径" help="缺省按抖音标题 55 字从严">
              {(id) => (
                <Select
                  id={id}
                  options={PLATFORM_OPTIONS}
                  value={platform}
                  onChange={(e) => setPlatform(e.target.value)}
                />
              )}
            </Field>
          </div>
          {variants.length ? (
            <div className="stack" style={{ gap: 8 }} data-testid="hook-list">
              {variants.map((v, i) => (
                <div className="hook-item" key={i}>
                  <span className="hook-text">{v.text}</span>
                  <span style={{ fontSize: 11.5, color: 'var(--ink-3)', fontVariantNumeric: 'tabular-nums' }}>
                    {v.chars}/{v.limit}
                  </span>
                  {v.passed ? (
                    <Chip tone="accent">通过</Chip>
                  ) : (
                    <Chip tone="danger">超限</Chip>
                  )}
                  <button
                    type="button"
                    className="iconbtn"
                    title="设为选题标题"
                    aria-label={`设为标题：${v.text}`}
                    disabled={applying !== null}
                    onClick={() => void apply(v.text)}
                  >
                    <Check size={15} />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-3)' }}>
              钩子是让人在 1 秒内想点进来的开头：反常识结论 / 数字承诺 / 提问 / 身份代入都可以混着来。
            </p>
          )}
        </div>
      ) : null}
      {errorText ? (
        <p className="sysfile danger" style={{ whiteSpace: 'pre-line', marginTop: 10 }} role="alert">
          {errorText}
        </p>
      ) : null}
    </Modal>
  )
}

export default HooksDialog
