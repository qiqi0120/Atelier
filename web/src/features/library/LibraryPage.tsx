/** SPEC-05 · 内容库页（照 design/prototype-v1.html 的 `#v-library`）。
 *
 * 布局：左项目树（.lib 第一列） + 右文件区 + 底部预览。
 * 行为要点：
 * - 面包屑逐级下钻，类型过滤 + 名称搜索，网格/列表双视图
 * - 预览按类型分派，HTML 走 sandbox iframe，媒体走 Range
 * - 删除一律走 DeleteDialog（后端口令 + 逐字输入文件名）
 * - 系统目录在树里置灰 + 「系统」chip，顶部常驻琥珀提示条
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Grid2X2, List, Plus, Trash2 } from 'lucide-react'
import { Button, Card, Chip, Input, Skeleton, toast } from '@/components'
import { PageHead } from '@/features/shared/PageHead'
import { DeleteDialog } from './DeleteDialog'
import type { DeleteTarget } from './DeleteDialog'
import { FileGrid } from './FileGrid'
import { FileList } from './FileList'
import { PreviewFooter, PreviewPane } from './PreviewPane'
import { ProjectTree } from './ProjectTree'
import { SystemFileNotice } from './SystemFileNotice'
import { KIND_TABS, useLibrary } from './useLibrary'

export function LibraryPage() {
  const nav = useNavigate()
  const lib = useLibrary()
  const [deleting, setDeleting] = useState<DeleteTarget | null>(null)
  const [newName, setNewName] = useState('')

  const { loc, tree, files, selected, loading, error } = lib
  const inSystem = loc.zone === '.session'

  const create = async () => {
    const name = newName.trim()
    if (!name) return
    try {
      await lib.createProject(name)
      setNewName('')
    } catch (e) {
      // api 层已 toast，这里不重复
      void e
    }
  }

  return (
    <div className="view-pad">
      <PageHead
        title="内容库"
        desc="文件系统是唯一真相源。成品与过程文件分区，路径可回溯。"
        actions={
          <>
            <Input
              sizeSm
              placeholder="按文件名搜索…"
              style={{ width: 170 }}
              aria-label="按文件名搜索"
              value={lib.qDraft}
              onChange={(e) => lib.setQDraft(e.target.value)}
            />
            <Button onClick={() => nav('/settings')}>选择输出目录</Button>
          </>
        }
      />

      <div className="lib">
        <Card
          title="项目目录"
          actions={<Chip tone="outline" mono>~/Atelier/outputs</Chip>}
          tight
        >
          {loading && !tree ? (
            <Skeleton height={140} />
          ) : (
            <>
              <ProjectTree
                projects={lib.projects}
                dirs={tree?.dirs ?? []}
                current={loc}
                onProject={lib.goProject}
                onZone={lib.goZone}
                onSub={lib.goSub}
              />
              <div className="row" style={{ gap: 6, marginTop: 12 }}>
                <Input
                  sizeSm
                  placeholder="新项目名"
                  aria-label="新项目名"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void create()
                  }}
                />
                <Button size="sm" icon={Plus} onClick={() => void create()}>
                  新建
                </Button>
              </div>
            </>
          )}
        </Card>

        <div className="stack">
          {/* 过滤 + 视图切换 */}
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <div className="tabs">
              {KIND_TABS.map((t) => (
                <button
                  key={t.key || 'all'}
                  type="button"
                  className={`tab${lib.kind === t.key ? ' on' : ''}`}
                  onClick={() => lib.setKind(t.key)}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="tabs" style={{ marginLeft: 'auto' }}>
              <button
                type="button"
                className={`tab${lib.view === 'grid' ? ' on' : ''}`}
                aria-label="网格视图"
                onClick={() => lib.setView('grid')}
              >
                <Grid2X2 size={13} />
              </button>
              <button
                type="button"
                className={`tab${lib.view === 'list' ? ' on' : ''}`}
                aria-label="列表视图"
                onClick={() => lib.setView('list')}
              >
                <List size={13} />
              </button>
            </div>
          </div>

          <Card
            title={lib.title}
            actions={
              <>
                <Chip tone="outline">{files.length} 项</Chip>
                <Button
                  size="sm"
                  onClick={() => toast.warn('发布中心的「从内容库挂载」将在下一批接上')}
                >
                  挂载到发布
                </Button>
                {loc.project && !inSystem ? (
                  <Button
                    size="sm"
                    variant="danger"
                    icon={Trash2}
                    onClick={() => setDeleting({ type: 'project', name: loc.project })}
                  >
                    删除项目
                  </Button>
                ) : null}
              </>
            }
          >
            {/* 面包屑：项目 → 分区 → 子目录，逐级回退（SPEC-05 §6 #2） */}
            {tree && tree.breadcrumb.length > 1 ? (
              <nav className="row" style={{ gap: 4, marginBottom: 10, fontSize: 11.5, flexWrap: 'wrap' }}>
                {tree.breadcrumb.map((c, i) => (
                  <span key={`${c.label}-${i}`} className="row" style={{ gap: 4 }}>
                    {i > 0 ? <span style={{ color: 'var(--muted)' }}>/</span> : null}
                    <button
                      type="button"
                      className="btn ghost sm"
                      style={{ color: i === tree.breadcrumb.length - 1 ? 'var(--ink)' : 'var(--muted)' }}
                      onClick={() => lib.goCrumb(i)}
                    >
                      <span className="btn-txt">{c.label}</span>
                    </button>
                  </span>
                ))}
                {loading ? <Skeleton width={54} height={14} /> : null}
              </nav>
            ) : null}

            <SystemFileNotice visible={Boolean(inSystem || tree?.is_system)} targetPath={tree?.path} />

            {error ? <p className="sysfile danger">{error}</p> : null}

            {loading && !files.length ? (
              <Skeleton height={120} />
            ) : lib.view === 'grid' ? (
              <FileGrid
                files={files}
                selectedPath={selected?.path ?? null}
                onSelect={lib.setSelected}
                onClear={() => {
                  lib.setKind('')
                  lib.setQDraft('')
                }}
              />
            ) : (
              <FileList
                files={files}
                selectedPath={selected?.path ?? null}
                onSelect={lib.setSelected}
                onClear={() => {
                  lib.setKind('')
                  lib.setQDraft('')
                }}
              />
            )}

            {selected && !selected.is_system ? (
              <div className="row" style={{ marginTop: 11, gap: 8 }}>
                <Button
                  size="sm"
                  variant="danger"
                  icon={Trash2}
                  onClick={() => setDeleting({ type: 'file', file: selected })}
                >
                  删除这个文件
                </Button>
              </div>
            ) : null}
          </Card>

          <Card
            title="预览"
            actions={
              <>
                {selected?.ext === 'html' ? <Chip tone="outline">sandbox iframe</Chip> : null}
                <Chip tone="outline" mono>
                  {selected?.name ?? '未选中'}
                </Chip>
              </>
            }
          >
            <PreviewPane file={selected} />
            <PreviewFooter file={selected} />
          </Card>
        </div>
      </div>

      <DeleteDialog
        target={deleting}
        onClose={() => setDeleting(null)}
        onDeleted={() => {
          setDeleting(null)
          void lib.refresh()
        }}
      />
    </div>
  )
}

export default LibraryPage
