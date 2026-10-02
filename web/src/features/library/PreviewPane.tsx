/** SPEC-05 §4 · PreviewPane：按类型分派预览。
 *
 * 安全红线（SPEC-05 §4「预览安全」）：
 * 1. HTML 一律进 `<iframe sandbox>`——不授予同源权限，页面里的脚本读不到宿主上下文。
 * 2. 图片 / 视频 / 音频的 src 指向 `/api/library/stream?path=…`（服务端按 Range 分段，
 *    不整文件预加载）。
 * 3. Markdown 走 `react-markdown`，**不挂 rehype-raw**，正文里的原始 HTML 不会被执行。
 */

import { useEffect, useState } from 'react'
import { AlertTriangle, Download, ExternalLink } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button, Chip, Skeleton, toast } from '@/components'
import { libraryApi, streamUrl } from './api'
import type { LibFile, PreviewResponse } from './types'

export type PreviewPaneProps = {
  file: LibFile | null
}

type Loaded = PreviewResponse | null

export function PreviewPane({ file }: PreviewPaneProps) {
  const [text, setText] = useState<Loaded>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const needsText = Boolean(
    file && file.kind === 'doc' && file.previewable && file.ext !== 'html' && file.ext !== 'htm',
  )

  useEffect(() => {
    setText(null)
    setErr(null)
    if (!file || !needsText) return
    let dead = false
    setLoading(true)
    libraryApi
      .preview(file.path)
      .then((res) => {
        if (dead) return
        setText(res)
        if (res.truncated) toast.warn(res.hint ?? '文件过大，已截断预览')
      })
      .catch((e: unknown) => {
        if (!dead) setErr(e instanceof Error ? e.message : '读取失败')
      })
      .finally(() => {
        if (!dead) setLoading(false)
      })
    return () => {
      dead = true
    }
  }, [file, needsText])

  return (
    <div className="preview" data-testid="preview-pane">
      {!file ? (
        <span className="help">选中一个文件就能预览。图片 / 视频走 Range 分段加载，不会一次性读整个文件。</span>
      ) : (
        <Body file={file} text={text} loading={loading} err={err} />
      )}
    </div>
  )
}

function Body({ file, text, loading, err }: { file: LibFile; text: Loaded; loading: boolean; err: string | null }) {
  const src = streamUrl(file.path)

  if (err) {
    return (
      <span className="sysfile danger" style={{ marginBottom: 0 }}>
        <AlertTriangle size={13} />
        {err}
      </span>
    )
  }
  if (loading) return <Skeleton width={280} height={150} />
  if (file.ext === 'html' || file.ext === 'htm') {
    return (
      <iframe
        // 空 sandbox：全能力禁用，且**不授予同源权限**，脚本读不到宿主页面
        sandbox=""
        src={src}
        title={`${file.name} 预览`}
        referrerPolicy="no-referrer"
        style={{ width: '100%', height: 300, border: 0, borderRadius: 8, background: 'var(--white)' }}
        data-testid="html-frame"
      />
    )
  }
  if (file.kind === 'image') {
    return <img src={src} alt={file.name} style={{ maxWidth: '100%', maxHeight: 320, objectFit: 'contain' }} />
  }
  if (file.kind === 'video') {
    return <video src={src} controls preload="metadata" style={{ maxWidth: '100%', maxHeight: 320 }} />
  }
  if (file.kind === 'audio') {
    return <AudioBox src={src} name={file.name} />
  }
  if (file.ext === 'md' || file.ext === 'markdown') {
    if (!text) return <Skeleton width={280} height={120} />
    return (
      <div style={{ width: '100%', maxHeight: 320, overflow: 'auto', textAlign: 'left' }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text.content}</ReactMarkdown>
      </div>
    )
  }
  if (file.previewable) {
    if (!text) return <Skeleton width={280} height={120} />
    return (
      <pre
        className="mono"
        style={{
          width: '100%',
          maxHeight: 320,
          overflow: 'auto',
          margin: 0,
          fontSize: 11.5,
          textAlign: 'left',
          whiteSpace: 'pre-wrap',
        }}
      >
        {text.content}
      </pre>
    )
  }
  return (
    <div className="stack" style={{ gap: 8, textAlign: 'center' }}>
      <AlertTriangle size={18} style={{ color: 'var(--muted)' }} />
      <span className="help">这个格式（.{file.ext || '无扩展名'}）没有内置预览，可以下载后用本地软件打开。</span>
    </div>
  )
}

/** 音频：`<audio>` + 静态波形占位（不做真实解码，M1 不引波形库） */
function AudioBox({ src, name }: { src: string; name: string }) {
  const bars = Array.from({ length: 28 }, (_, i) => 6 + ((i * 7919) % 26))
  return (
    <div className="stack" style={{ gap: 10, width: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 34, justifyContent: 'center' }}>
        {bars.map((h, i) => (
          <span
            key={i}
            style={{ width: 3, height: h, borderRadius: 2, background: 'var(--kind-aud)', opacity: 0.55 }}
          />
        ))}
      </div>
      <audio src={src} controls preload="metadata" style={{ width: '100%' }} aria-label={name} />
    </div>
  )
}

export type PreviewFooterProps = { file: LibFile | null }

export function PreviewFooter({ file }: PreviewFooterProps) {
  if (!file) return null
  return (
    <div className="row" style={{ marginTop: 11, gap: 8, flexWrap: 'wrap' }}>
      <span className="help">
        {file.is_system
          ? '系统文件受保护，禁止删除；预览只读。'
          : '媒体走 Range 分段加载，不会整文件预取。'}
      </span>
      <Chip tone="outline" mono style={{ marginLeft: 'auto' }}>
        {file.size_human}
      </Chip>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => window.open(streamUrl(file.path), '_blank', 'noopener')}
        icon={ExternalLink}
      >
        原文件
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => {
          const a = document.createElement('a')
          a.href = streamUrl(file.path, true)
          a.download = file.name
          a.click()
          toast.ok('已开始下载')
        }}
        icon={Download}
      >
        下载
      </Button>
    </div>
  )
}

export default PreviewPane
