import { useEffect, useState } from 'react'
import { Button, Input, Modal, toast } from '@/components'
import { publishApi } from './types'

export type SmsDialogProps = {
  recordId: string | null
  onClose: () => void
  /** 提交成功后回调（父组件负责刷新发布状态） */
  onSubmitted: () => void
}

/**
 * 短信验证码弹窗（F-G16 / SPEC-06 §6）。
 *
 * **5 分钟倒计时**：从后端 `expires_in` 起算，后端是唯一真相源
 * （前端自己起计时器会在后台标签页里漂）。
 * ★ 真实验证码校验属 M4 批次，本批只校验格式与有效期。
 */
export function SmsDialog({ recordId, onClose, onSubmitted }: SmsDialogProps) {
  const [code, setCode] = useState('')
  const [left, setLeft] = useState(0)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!recordId) return
    let alive = true
    const tick = async () => {
      try {
        const st = await publishApi.smsState(recordId)
        if (!alive) return
        setLeft(st.expires_in)
        if (st.expires_in <= 0) return
      } catch {
        /* 轮询失败不弹窗打扰：倒计时归零自然关闭 */
      }
    }
    void tick()
    const timer = window.setInterval(tick, 1000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [recordId])

  useEffect(() => {
    if (recordId) setCode('')
  }, [recordId])

  const submit = async () => {
    if (!recordId) return
    setBusy(true)
    try {
      await publishApi.submitSms(recordId, code)
      toast('验证码已提交（真实校验属 M4 批次）', 'ok')
      onSubmitted()
    } catch {
      /* ApiError 已自动 toast */
    } finally {
      setBusy(false)
    }
  }

  const expired = left <= 0

  return (
    <Modal
      open={Boolean(recordId)}
      onClose={onClose}
      title="平台要求短信验证码"
      sub={expired ? '验证码已过期' : `${Math.floor(left / 60)} 分 ${String(left % 60).padStart(2, '0')} 秒后失效`}
      closeOnScrim={false}
      footer={
        <Button variant="ghost" onClick={onClose}>
          取消
        </Button>
      }
      onOk={submit}
      okText={busy ? '提交中…' : '提交验证码'}
    >
      <div className="stack" style={{ gap: 11 }}>
        <Input
          label="短信验证码"
          help="6 位数字。抖音等平台在高频发布时会要求二次验证。"
          value={code}
          maxLength={6}
          inputMode="numeric"
          mono
          autoFocus
          disabled={expired}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
          data-testid="sms-code"
        />
        {expired ? <p className="err">验证码已过期，请关掉弹窗后重新发起一次发布。</p> : null}
        <p className="help">
          本批只校验格式与有效期；**真实平台的验证码校验属 M4 批次**（需要真实账号登录态）。
        </p>
      </div>
    </Modal>
  )
}

export default SmsDialog
