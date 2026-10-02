/** SPEC-05 §4 · FileTile：网格视图的单个文件（缩略图 + 文件名 + 尺寸 + 大小）。 */

import { FileText, Film, Image as ImageIcon, Mic } from 'lucide-react'
import { streamUrl } from './api'
import type { LibFile, LibKind } from './types'

/** 类型 → 图标 / 颜色 token（token 已在 tokens.css 冻结，禁止字面色值） */
export const KIND_STYLE: Record<LibKind, { Icon: typeof FileText; color: string; short: string }> = {
  image: { Icon: ImageIcon, color: 'var(--kind-img)', short: 'IMG' },
  video: { Icon: Film, color: 'var(--kind-vid)', short: 'VID' },
  audio: { Icon: Mic, color: 'var(--kind-aud)', short: 'AUD' },
  doc: { Icon: FileText, color: 'var(--kind-doc)', short: 'DOC' },
  file: { Icon: FileText, color: 'var(--muted)', short: 'FILE' },
}

export function sizeLabel(f: LibFile): string {
  const dim = f.width && f.height ? `${f.width}×${f.height}` : f.duration_human
  return [dim, f.size_human].filter(Boolean).join(' · ')
}

export type FileTileProps = {
  file: LibFile
  selected: boolean
  onSelect: (file: LibFile) => void
}

export function FileTile({ file, selected, onSelect }: FileTileProps) {
  const { Icon, color } = KIND_STYLE[file.kind]
  return (
    <button
      type="button"
      className={`tile${selected ? ' sel' : ''}`}
      onClick={() => onSelect(file)}
      title={file.rel_to_root}
      data-testid={`tile-${file.name}`}
    >
      <span className="th">
        {file.kind === 'image' ? (
          <img
            src={streamUrl(file.path)}
            alt={file.name}
            loading="lazy"
            style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
          />
        ) : (
          <span
            style={{
              width: 44,
              height: 44,
              borderRadius: 10,
              display: 'grid',
              placeItems: 'center',
              background: 'var(--surface-2)',
              color,
            }}
          >
            <Icon size={18} />
          </span>
        )}
        {file.is_system ? (
          <span
            style={{
              position: 'absolute',
              top: 5,
              right: 5,
              fontSize: 9,
              padding: '1px 5px',
              borderRadius: 6,
              background: 'var(--surface-3)',
              color: 'var(--muted)',
            }}
          >
            系统
          </span>
        ) : null}
      </span>
      <span className="tb" style={{ display: 'block', textAlign: 'left' }}>
        <b>{file.name}</b>
        <span>{sizeLabel(file)}</span>
      </span>
    </button>
  )
}

export default FileTile
