import { useNavigate } from 'react-router-dom'
import { FolderOpen, ImageIcon, SendHorizonal } from 'lucide-react'
import { Button } from '@/components'
import type { ArtifactView } from './types'

export type ArtifactCardProps = {
  artifacts: ArtifactView[]
  /** 只显示这个分区（原型里产物卡与门禁块同属一个卡片） */
  title?: string
}

/**
 * 产物卡：路径渲染为**可点击 chip**，点一下直达内容库并带上路径（UI-SPEC 规则 10）。
 * 路径原样显示 `outputs/<项目>/<分区>/<文件>`，不做任何改写。
 */
export function ArtifactCard({ artifacts, title }: ArtifactCardProps) {
  const navigate = useNavigate()
  if (!artifacts.length) return null
  const dir = artifacts[0].path.split('/').slice(0, -1).join('/')
  const kinds = new Set(artifacts.map((a) => a.kind))
  const heading =
    title ??
    (kinds.size === 1 && kinds.has('image')
      ? `视觉产出 ${artifacts.length} 张`
      : `产物 ${artifacts.length} 个`)

  return (
    <div className="artifact">
      <div className="ah">
        <ImageIcon size={13} />
        {heading}
        <span className="sp" style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <Button
            size="sm"
            variant="ghost"
            icon={FolderOpen}
            onClick={() => navigate(`/library?path=${encodeURIComponent(dir)}`)}
          >
            打开目录
          </Button>
          <Button size="sm" icon={SendHorizonal} onClick={() => navigate('/publish')}>
            去发布
          </Button>
        </span>
      </div>
      <div className="ab">
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          {artifacts.map((a) => (
            <span
              key={a.path}
              className="path"
              role="button"
              tabIndex={0}
              title={`在内容库里定位 ${a.path}`}
              onClick={() => navigate(`/library?path=${encodeURIComponent(a.path)}`)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') navigate(`/library?path=${encodeURIComponent(a.path)}`)
              }}
            >
              {a.path}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

export default ArtifactCard
