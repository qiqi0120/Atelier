/** SPEC-05 §4 · ProjectTree：项目 → 成品 / 素材 / .session（系统目录置灰 + 「系统」chip）。 */

import { ChevronRight, Folder, FolderOpen } from 'lucide-react'
import { Chip } from '@/components'
import type { LibProject, LibZone } from './types'

export type ProjectTreeProps = {
  projects: LibProject[]
  /** 当前 zone 下的子目录（由 /library/tree 返回，Page 透传） */
  dirs?: { name: string; path: string; is_system: boolean }[]
  current: { project: string; zone: LibZone; sub: string }
  onProject: (project: string) => void
  onZone: (zone: LibZone) => void
  onSub: (path: string) => void
}

/** 系统目录（`.session/`）永远不能删，UI 上置灰并挂「系统」chip（UI-SPEC 规则 20） */
const ZONES: { key: LibZone; countKey: 'product_count' | 'material_count' | 'system_count'; system: boolean }[] = [
  { key: '成品', countKey: 'product_count', system: false },
  { key: '素材', countKey: 'material_count', system: false },
  { key: '.session', countKey: 'system_count', system: true },
]

export function ProjectTree({ projects, dirs = [], current, onProject, onZone, onSub }: ProjectTreeProps) {
  if (projects.length === 0) {
    return <p className="help">还没有项目。到对话里产出一份内容，或新建一个项目目录。</p>
  }
  return (
    <div className="tree">
      {projects.map((p) => {
        const open = p.name === current.project
        return (
          <div key={p.name}>
            <button
              type="button"
              className={`n${open ? ' on' : ''}`}
              onClick={() => onProject(p.name)}
              aria-expanded={open}
              data-testid={`project-${p.name}`}
            >
              {open ? <FolderOpen size={14} /> : <Folder size={14} />}
              {p.name}
              <span className="c">{p.file_count}</span>
            </button>
            {open
              ? ZONES.map((z) => {
                  const on = current.zone === z.key && !current.sub
                  return (
                    <button
                      type="button"
                      key={z.key}
                      className={`n sub${on ? ' on' : ''}`}
                      // 系统目录只读：仍可浏览看内容，但视觉置灰
                      style={z.system ? { color: 'var(--muted)' } : undefined}
                      onClick={() => onZone(z.key)}
                      data-testid={`zone-${z.key}`}
                      aria-current={on}
                    >
                      <Folder size={12} />
                      {z.key}
                      <span className="c">{p[z.countKey]}</span>
                      {z.system ? <Chip tone="outline" xs>系统</Chip> : null}
                    </button>
                  )
                })
              : null}
          </div>
        )
      })}
      {/* 当前 zone 下的子目录逐级下钻（面包屑的第二层） */}
      <SubDirs dirs={dirs} current={current} onSub={onSub} />
      <p className="help" style={{ marginTop: 10 }}>
        <ChevronRight size={11} style={{ verticalAlign: -1 }} /> 点分区进二级目录；再点面包屑回上一级
      </p>
    </div>
  )
}

/** 二级子目录：数据由 Page 传进来（复用同一份 /library/tree 响应，不再发请求） */
export function SubDirs({
  dirs,
  current,
  onSub,
}: {
  dirs: { name: string; path: string; is_system: boolean }[]
  current: { sub: string }
  onSub: (path: string) => void
}) {
  if (!dirs.length) return null
  return (
    <>
      {dirs.map((d) => (
        <button
          type="button"
          key={d.path}
          className={`n sub${current.sub === d.name ? ' on' : ''}`}
          style={{ paddingLeft: 40, ...(d.is_system ? { color: 'var(--muted)' } : {}) }}
          onClick={() => onSub(d.path)}
        >
          <Folder size={12} />
          {d.name}
          {d.is_system ? <Chip tone="outline" xs>系统</Chip> : null}
        </button>
      ))}
    </>
  )
}

export default ProjectTree
