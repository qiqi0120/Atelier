import { useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Eye, Sparkles, X } from 'lucide-react'
import { Button, Card, Chip, toast } from '@/components'
import { countChars } from './api'
import type { DimKey, PreviewResult } from './api'

/** UI-SPEC §6 / spec §6：编辑即实时预览，300ms debounce */
const PREVIEW_DEBOUNCE_MS = 300

export type ProfileEditorProps = {
  dim: DimKey
  title: string
  hint: string
  value: string
  dirty: boolean
  saving: boolean
  generalMode: boolean
  onChange: (next: string) => void
  onSave: () => void
  onPreview: () => Promise<PreviewResult>
}

/**
 * 右编辑区：Markdown 编辑 + 实时渲染预览 + 字数计数。
 *
 * 预览用 react-markdown（UI-SPEC §7 约束 3），**不**用 iframe sandbox——
 * 那是 HTML 预览的要求，这里渲染的是用户自己的 Markdown 文本。
 */
export function ProfileEditor({
  dim,
  title,
  hint,
  value,
  dirty,
  saving,
  generalMode,
  onChange,
  onSave,
  onPreview,
}: ProfileEditorProps) {
  // 预览单独一份 state：输入时不阻塞打字，防抖只挡渲染
  const [preview, setPreview] = useState(value)
  const [showPrompt, setShowPrompt] = useState(false)
  const [prompt, setPrompt] = useState<PreviewResult | null>(null)

  useEffect(() => {
    const t = setTimeout(() => setPreview(value), PREVIEW_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [value])

  // 切维度立刻重置，不等 300ms（否则会闪一下上一维的内容）
  useEffect(() => {
    setPreview(value)
    setShowPrompt(false)
    setPrompt(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dim])

  const count = useMemo(() => countChars(value), [value])
  const stale = countChars(preview) !== count

  const openPrompt = async () => {
    try {
      setPrompt(await onPreview())
      setShowPrompt(true)
    } catch {
      /* lib/api 已经 toast 过错误了，这里不重复提示 */
    }
  }

  return (
    <Card
      title={`${title} · ${dim}`}
      actions={
        <>
          <Chip tone="outline">Markdown</Chip>
          {generalMode ? <Chip tone="warn">通用模式 · 本轮不注入</Chip> : null}
          <Button
            size="sm"
            icon={Sparkles}
            disabled
            disabledReason="AI 帮我补全排在 M2：要先抓取社媒链接内容（spec §1 F-A3）"
          >
            AI 帮我补全
          </Button>
          <Button size="sm" variant="primary" loading={saving} disabled={!dirty} onClick={onSave}>
            保存
          </Button>
        </>
      }
    >
      <div className="split">
        <div>
          <div className="field" style={{ marginBottom: 10 }}>
            <label htmlFor="dimEdit">编辑（Markdown）</label>
            <textarea
              id="dimEdit"
              className="inp mono"
              rows={12}
              style={{ fontSize: 12.5 }}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              placeholder={PLACEHOLDERS[dim]}
            />
          </div>
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <span className="help">{hint}</span>
            <span className="chip o mono" style={{ marginLeft: 'auto' }}>
              {count} 字
            </span>
          </div>
        </div>

        <div>
          <div className="row lbl" style={{ marginBottom: 7, gap: 8 }}>
            渲染预览
            {stale ? <span className="help">渲染中…</span> : null}
          </div>
          <div className="mdview md" data-testid="dim-preview">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{preview || '*（这一维还是空的）*'}</ReactMarkdown>
          </div>
        </div>
      </div>

      <div className="row" style={{ marginTop: 10, gap: 8 }}>
        <Button size="sm" variant="ghost" icon={Eye} onClick={() => void openPrompt()}>
          预览 system_prompt
        </Button>
        <span className="help">看这一轮真正会注入的内容——通用模式下应该是空的</span>
      </div>

      {showPrompt ? (
        <div style={{ marginTop: 10 }}>
          <div className="row lbl" style={{ marginBottom: 6, gap: 8 }}>
            本轮 system_prompt
            <Chip tone={prompt?.injected ? 'accent' : 'warn'}>{prompt?.reason ?? ''}</Chip>
            <button
              type="button"
              className="iconbtn"
              style={{ marginLeft: 'auto' }}
              aria-label="关闭预览"
              onClick={() => setShowPrompt(false)}
            >
              <X size={13} />
            </button>
          </div>
          <pre
            className="inp mono"
            data-testid="system-prompt"
            style={{ maxHeight: 260, overflow: 'auto', whiteSpace: 'pre-wrap', fontSize: 12 }}
          >
            {prompt?.system_prompt ?? ''}
          </pre>
          {prompt && prompt.leaked_dims.length > 0 ? (
            <div className="help" style={{ color: 'var(--danger)' }}>
              自检异常：{prompt.leaked_dims.join('、')} 的正文混进了不该出现的地方。
            </div>
          ) : null}
        </div>
      ) : null}

      {dirty ? (
        <div className="help" style={{ marginTop: 8 }}>
          有未保存的改动。保存后 toast 会告诉你什么时候生效。
        </div>
      ) : null}
    </Card>
  )
}

/** 保存成功后的统一文案（UI-SPEC §5：下一轮对话立即生效） */
export const SAVED_TOAST = '已保存 · 下一轮对话立即生效'

export function savedToast() {
  toast.ok(SAVED_TOAST)
}

const PLACEHOLDERS: Record<DimKey, string> = {
  identity: '## 我是谁\n\n独立内容创作者，一个人运营 3 个账号，主力做「AI + 内容效率」。\n\n- 主阵地：小红书\n- 次阵地：抖音',
  style: '## 怎么说话\n\n- 短句为主\n- 先给结论，再讲原因\n- 不用「震惊 / 必看」这类极限词',
  audience: '## 我在写给谁\n\n- 22–32 岁的内容从业者\n- 已经在用 AI，但觉得产出没变好',
  platform_rules: '## 平台约束\n\n| 平台 | 内容形态 | 字数 |\n|---|---|---|\n| 小红书 | 图文 3–9 张 | 1000 |',
  preferences: '## 我不要什么\n\n- 不写「AI 生成的」这种内容\n- 不做未实测的产品对比',
  memories: '长期记忆在下面单独管理，这里改的是「沉淀结论」的说明。',
}

export default ProfileEditor
