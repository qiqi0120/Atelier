/** SPEC-11 §4 · F-D10 竞品分析弹层：粘贴竞品内容 → 选题/格式/规律 三列表。
 *
 * 列表里的选题可逐条存入选题库（走既有 POST /topics，source=manual、
 * source_ref=竞品分析，SPEC-11 §0 D2——后端零新端点）。
 */

import { useState } from 'react'
import { Button, Field, Modal, Textarea, toast } from '@/components'
import { useAtelier } from '@/lib/store'
import { describeError } from '@/lib/gates'
import { topicsApi } from '@/features/topics/api'
import { analyticsApi } from './api'
import type { CompetitorResult } from './types'

export type CompetitorDialogProps = {
  open: boolean
  onClose: () => void
}

const MIN_CHARS = 40

export function CompetitorDialog({ open, onClose }: CompetitorDialogProps) {
  const profile = useAtelier((s) => s.profile)
  const profileId = profile && !profile.generalMode ? profile.id : undefined

  const [text, setText] = useState('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<CompetitorResult | null>(null)
  const [saved, setSaved] = useState<Set<string>>(new Set())
  const [errorText, setErrorText] = useState('')

  const close = () => {
    setResult(null)
    setSaved(new Set())
    setText('')
    setErrorText('')
    onClose()
  }

  const run = async () => {
    setRunning(true)
    setErrorText('')
    try {
      setResult(await analyticsApi.competitor(text.trim(), profileId))
    } catch (e) {
      setErrorText(describeError(e))
    } finally {
      setRunning(false)
    }
  }

  const saveTopic = async (title: string) => {
    await topicsApi.create({ title, source: 'manual', source_ref: '竞品分析' })
    setSaved((cur) => new Set(cur).add(title))
    toast.ok('已存入选题库（待做列）')
  }

  const cols: { key: keyof Pick<CompetitorResult, 'topics' | 'formats' | 'patterns'>; label: string; savable: boolean }[] = [
    { key: 'topics', label: 'TA 在写的选题', savable: true },
    { key: 'formats', label: 'TA 用的格式', savable: false },
    { key: 'patterns', label: '爆款规律', savable: false },
  ]

  return (
    <Modal
      open={open}
      onClose={close}
      title="竞品分析"
      sub="粘贴竞品内容，反推 TA 的选题策略、格式与爆款规律"
      width={640}
      footer={
        result ? (
          <Button variant="primary" onClick={close}>
            完成
          </Button>
        ) : (
          <>
            <Button onClick={close}>取消</Button>
            <Button
              variant="primary"
              disabled={text.trim().length < MIN_CHARS || running}
              loading={running}
              disabledReason={
                text.trim().length < MIN_CHARS ? `至少 ${MIN_CHARS} 字，多贴几条同类内容` : undefined
              }
              onClick={() => void run()}
            >
              开始分析
            </Button>
          </>
        )
      }
    >
      {result ? (
        <div className="stack" style={{ gap: 14 }}>
          {cols.map((col) => (
            <div key={col.key}>
              <p style={{ margin: '0 0 6px', fontSize: 12.5, fontWeight: 600, color: 'var(--ink-2)' }}>
                {col.label}
              </p>
              <div className="stack" style={{ gap: 6 }}>
                {result[col.key].map((item) => (
                  <div key={item} className="row" style={{ gap: 8, fontSize: 13, alignItems: 'center' }}>
                    <span style={{ flex: 1 }}>{item}</span>
                    {col.savable && !saved.has(item) ? (
                      <Button size="sm" variant="ghost" onClick={() => void saveTopic(item)}>
                        存入选题库
                      </Button>
                    ) : null}
                    {col.savable && saved.has(item) ? (
                      <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>已存入</span>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <Field label="竞品原文" required help={`至少 ${MIN_CHARS} 字；贴 TA 表现最好的一条或多条拼接`}>
          {(id) => (
            <Textarea
              id={id}
              rows={8}
              placeholder={'粘贴竞品的完整文案……\n（可多条拼接，分析的是结构不是文字本身）'}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          )}
        </Field>
      )}
      {errorText ? (
        <p className="sysfile danger" style={{ whiteSpace: 'pre-line' }} role="alert">
          {errorText}
        </p>
      ) : null}
    </Modal>
  )
}

export default CompetitorDialog
