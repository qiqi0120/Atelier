import { useState } from 'react'
import { Check, CircleHelp } from 'lucide-react'
import type { QuestionView } from './types'

export type QuestionCardProps = {
  question: QuestionView
  onAnswer: (questionId: string, optionKey: string, label: string) => void
}

/**
 * 问答题卡片（F-B7 / UI-SPEC 规则 7）：
 * 点完选项 → 全部锁定、折叠成「已确认 + 你的选择」，**本会话不再出现**
 * （服务端也会丢弃同 question_id 的重复提问，前端锁定只是第二道保险）。
 */
export function QuestionCard({ question, onAnswer }: QuestionCardProps) {
  const [picked, setPicked] = useState<string | null>(question.answered?.option_key ?? null)
  const locked = Boolean(question.answered) || picked !== null
  const chosen = question.answered ?? question.options.find((o) => o.key === picked)

  if (locked) {
    return (
      <div className="qcard">
        <div className="qt">
          <CircleHelp size={14} />
          {question.text}
        </div>
        <div className="qdone">
          <Check size={13} />
          已确认 · 你的选择：{chosen?.label ?? picked}
        </div>
      </div>
    )
  }

  return (
    <div className="qcard">
      <div className="qt">
        <CircleHelp size={14} />
        {question.text}
      </div>
      <div className="qopts">
        {question.options.map((o) => (
          <button
            key={o.key}
            type="button"
            className="qopt"
            onClick={() => {
              setPicked(o.key)
              onAnswer(question.question_id, o.key, o.label)
            }}
          >
            <span className="k">{o.key}</span>
            {o.label}
          </button>
        ))}
      </div>
      <div className="help" style={{ marginTop: 8 }}>
        已答此题在本会话内不会再次出现
      </div>
    </div>
  )
}

export default QuestionCard
