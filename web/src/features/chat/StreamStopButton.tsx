export type StreamStopButtonProps = {
  onStop: () => void
  stopping?: boolean
}

/**
 * 生成中替换发送按钮（UI-SPEC 规则 5）。
 * 点了立刻本地停打字（不等服务端事件），所以视觉停止远快于 2s 上限（F-B5）。
 */
export function StreamStopButton({ onStop, stopping = false }: StreamStopButtonProps) {
  return (
    <button type="button" className="stopbtn" onClick={onStop} disabled={stopping} title="停止生成（保留已生成内容）">
      <span className="s" style={{ width: 8, height: 8, borderRadius: 2, background: 'currentColor' }} />
      {stopping ? '停止中…' : '停止生成'}
    </button>
  )
}

export default StreamStopButton
