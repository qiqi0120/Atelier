/** SPEC-05 §4 · FileList：列表视图（密集，适合路径/尺寸核对）。 */

import { Chip } from '@/components'
import { streamUrl } from './api'
import { KIND_STYLE, sizeLabel } from './FileTile'
import type { LibFile } from './types'

export type FileListProps = {
  files: LibFile[]
  selectedPath: string | null
  onSelect: (file: LibFile) => void
  onClear: () => void
}

export function FileList({ files, selectedPath, onSelect, onClear }: FileListProps) {
  if (!files.length) {
    return (
      <p className="help">
        没有匹配的文件。
        <button type="button" className="btn ghost sm" style={{ marginLeft: 8 }} onClick={onClear}>
          <span className="btn-txt">清空筛选</span>
        </button>
      </p>
    )
  }
  return (
    <div data-testid="file-list">
      {files.map((f) => {
        const { Icon, color, short } = KIND_STYLE[f.kind]
        return (
          <div
            key={f.path}
            className={`list-row${f.path === selectedPath ? ' sel' : ''}`}
            onClick={() => onSelect(f)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') onSelect(f)
            }}
            role="button"
            tabIndex={0}
            title={f.rel_to_root}
            data-testid={`row-${f.name}`}
          >
            <span className="ic" style={{ background: color }}>
              {short}
            </span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <span className="nm" style={{ display: 'block', fontSize: 12.5, fontWeight: 500 }}>
                {f.name}
              </span>
              <span className="mono" style={{ display: 'block', fontSize: 10.5, color: 'var(--muted)' }}>
                {f.rel_to_root}
              </span>
            </span>
            <span className="mono" style={{ fontSize: 10.5, color: 'var(--muted)' }}>
              {sizeLabel(f)}
            </span>
            {f.is_system ? <Chip tone="outline" xs>系统</Chip> : null}
            {f.kind === 'image' ? (
              <img
                src={streamUrl(f.path)}
                alt=""
                width={30}
                height={30}
                loading="lazy"
                style={{ borderRadius: 6, objectFit: 'cover' }}
              />
            ) : (
              <Icon size={14} style={{ color: 'var(--muted)' }} />
            )}
          </div>
        )
      })}
    </div>
  )
}

export default FileList
