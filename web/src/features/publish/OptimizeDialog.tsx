/** SPEC-14 §2 · F-G19 平台优化建议弹层。
 *
 * 三态模式（running/result/errorText，close() 重置）；画像注入走 useAtelier。
 * 结果分四组：建议标题（每条可一键替换草稿标题）/ 话题标签 / 发布时机 / 注意事项。
 * 502=AI 违约、422=GateBlocked → describeError 在弹层内渲染改法（role="alert"）。
 */

import { useState } from 'react'
import { Wand2 } from 'lucide-react'
import { Button, Chip, Modal, Select, toast } from '@/components'
import { useAtelier } from '@/lib/store'
import { describeError } from '@/lib/gates'
import { publishApi } from './types'
import type { OptimizeResult, PlatformMeta, PublishDraft } from './types'

export type OptimizeDialogProps = {
  open: boolean
  onClose: () => void
  draft: PublishDraft | null
  /** 平台元数据（只用来把 platform key 显示成中文名） */
  platforms: PlatformMeta[]
  /** 点「替换标题」后由父组件落库（patch 草稿 + 自动保存） */
  onReplaceTitle: (title: string) => void
}

export function OptimizeDialog({ open, onClose, draft, platforms, onReplaceTitle }: OptimizeDialogProps) {
  const profile = useAtelier((s) => s.profile)
  const profileId = profile && !profile.generalMode ? profile.id : undefined

  /** 已适配的平台才有优化意义（候选 = draft.variants 里 adapted 的） */
  const adapted = draft?.variants.filter((v) => v.adapted) ?? []
  const [platform, setPlatform] = useState('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<OptimizeResult | null>(null)
  const [errorText, setErrorText] = useState('')

  const effectivePlatform = platform || adapted[0]?.platform || ''
  const options = adapted.map((v) => ({
    value: v.platform,
    label: platforms.find((p) => p.platform === v.platform)?.name ?? v.platform,
  }))

  const close = () => {
    setResult(null)
    setErrorText('')
    setPlatform('')
    onClose()
  }

  const run = async () => {
    if (!draft || !effectivePlatform) return
    setRunning(true)
    setErrorText('')
    try {
      setResult(
        await publishApi.optimize({
          platform: effectivePlatform,
          title: draft.title,
          body: draft.body,
          profile_id: profileId,
        }),
      )
    } catch (e) {
      setErrorText(describeError(e))
    } finally {
      setRunning(false)
    }
  }

  const replace = (t: string) => {
    onReplaceTitle(t)
    toast.ok('已替换标题')
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="平台优化建议"
      sub={
        profileId
          ? `基于画像「${profile?.name}」针对单平台给建议；只读不落库`
          : '通用模式（未绑定画像），建议会如实标注'
      }
      width={560}
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
              loading={running}
              disabled={!draft || adapted.length === 0}
              disabledReason="这份草稿还没有已适配的平台，先做一次适配"
              onClick={() => void run()}
            >
              生成建议
            </Button>
          </>
        )
      }
    >
      {!result ? (
        <div className="stack" style={{ gap: 10 }}>
          {adapted.length > 0 ? (
            <Select
              label="针对哪个已适配平台"
              value={effectivePlatform}
              options={options}
              onChange={(e) => setPlatform(e.target.value)}
            />
          ) : (
            <p className="help" style={{ margin: 0 }}>
              这份草稿还没有已适配的平台——先回母版卡点「重新适配」，再来拿单平台优化建议。
            </p>
          )}
          <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-2)' }}>
            <Wand2 size={13} aria-hidden style={{ verticalAlign: -2, marginRight: 4 }} />
            携带草稿当前的标题与正文，按该平台的公开约束给标题 / 话题 / 时机 / 注意事项四组建议；
            满意的标题可一键替换回草稿。
          </p>
        </div>
      ) : null}

      {result ? (
        <div className="stack" style={{ gap: 12, maxHeight: '58vh', overflow: 'auto' }}>
          <div>
            <p style={{ margin: '0 0 6px', fontSize: 12.5, fontWeight: 600, color: 'var(--ink-2)' }}>
              建议标题（点「替换标题」写回草稿）
            </p>
            <div className="stack" style={{ gap: 6 }}>
              {result.titles.map((t) => (
                <div key={t} className="row" style={{ gap: 8, alignItems: 'center' }}>
                  <span style={{ flex: 1, minWidth: 0, fontSize: 13 }}>{t}</span>
                  <Button size="sm" variant="ghost" onClick={() => replace(t)}>
                    替换标题
                  </Button>
                </div>
              ))}
            </div>
          </div>
          <div>
            <p style={{ margin: '0 0 6px', fontSize: 12.5, fontWeight: 600, color: 'var(--ink-2)' }}>
              话题标签
            </p>
            <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
              {result.tags.map((t) => (
                <Chip key={t} tone="outline" xs>
                  #{t}
                </Chip>
              ))}
            </div>
          </div>
          <div>
            <p style={{ margin: '0 0 6px', fontSize: 12.5, fontWeight: 600, color: 'var(--ink-2)' }}>
              发布时机
            </p>
            <p style={{ margin: 0, fontSize: 13 }}>{result.timing}</p>
          </div>
          <div>
            <p style={{ margin: '0 0 6px', fontSize: 12.5, fontWeight: 600, color: 'var(--ink-2)' }}>
              注意事项
            </p>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
              {result.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}

      {errorText ? (
        <p className="sysfile danger" style={{ whiteSpace: 'pre-line' }} role="alert">
          {errorText}
        </p>
      ) : null}
    </Modal>
  )
}

export default OptimizeDialog
