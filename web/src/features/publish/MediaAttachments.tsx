import { Plus, X } from 'lucide-react'
import { Button, Card, EmptyState } from '@/components'

export type MediaAttachmentsProps = {
  attachments: string[]
  onRemove: (path: string) => void
  onAdd: () => void
  onGoLibrary: () => void
}

/** 媒体附件：从内容库挂载（F-G14）。逐个可移除。 */
export function MediaAttachments({ attachments, onRemove, onAdd, onGoLibrary }: MediaAttachmentsProps) {
  return (
    <Card
      title="媒体附件"
      actions={
        <Button size="sm" variant="ghost" onClick={onGoLibrary}>
          从内容库挂载
        </Button>
      }
    >
      {attachments.length === 0 ? (
        <EmptyState
          title="还没有挂载素材"
          description="小红书和公众号必须有封面图；抖音只接受视频。素材从内容库挂载，不在这里上传。"
          action={
            <Button variant="primary" onClick={onGoLibrary}>
              去内容库选素材
            </Button>
          }
        />
      ) : (
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          {attachments.map((a) => (
            <div className="attach-item" key={a} data-testid="attach-item">
              <span className="chip o mono" style={{ height: 18 }}>
                {kindOf(a)}
              </span>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{baseName(a)}</span>
              <button
                type="button"
                className="iconbtn"
                style={{ width: 16, height: 16 }}
                aria-label={`移除附件 ${baseName(a)}`}
                onClick={() => onRemove(a)}
              >
                <X size={12} />
              </button>
            </div>
          ))}
          <Button size="sm" variant="ghost" icon={Plus} onClick={onAdd}>
            + 添加
          </Button>
        </div>
      )}
    </Card>
  )
}

const IMAGE = ['png', 'jpg', 'jpeg', 'webp', 'heic', 'gif']
const VIDEO = ['mp4', 'mov', 'm4v', 'webm', 'mkv']

function extOf(path: string): string {
  const p = path.toLowerCase()
  const dot = p.lastIndexOf('.')
  return dot >= 0 ? p.slice(dot + 1) : ''
}

function kindOf(path: string): string {
  const e = extOf(path)
  if (IMAGE.includes(e)) return 'IMG'
  if (VIDEO.includes(e)) return 'VID'
  if (e === 'srt' || e === 'vtt' || e === 'ass') return 'SRT'
  return e.slice(0, 3).toUpperCase() || 'FILE'
}

function baseName(path: string): string {
  const parts = path.split(/[\\/]/)
  return parts[parts.length - 1] || path
}

export default MediaAttachments
