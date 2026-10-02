/** SPEC-05 §4 · FileGrid：网格视图。 */

import { EmptyState } from '@/components'
import { FileTile } from './FileTile'
import type { LibFile } from './types'

export type FileGridProps = {
  files: LibFile[]
  selectedPath: string | null
  onSelect: (file: LibFile) => void
  onClear: () => void
}

export function FileGrid({ files, selectedPath, onSelect, onClear }: FileGridProps) {
  if (!files.length) {
    return (
      <EmptyState
        title="这个分区还没有文件"
        description="成品 / 素材里的产物会按项目自动归档。换个分区或清空筛选看看。"
        action={
          <button type="button" className="btn ghost" onClick={onClear}>
            <span className="btn-txt">清空筛选</span>
          </button>
        }
      />
    )
  }
  return (
    <div className="file-grid" data-testid="file-grid">
      {files.map((f) => (
        <FileTile key={f.path} file={f} selected={f.path === selectedPath} onSelect={onSelect} />
      ))}
    </div>
  )
}

export default FileGrid
