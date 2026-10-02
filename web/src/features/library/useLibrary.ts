/** SPEC-05 §1–§2 · 内容库页状态（单一 hook，页面只管渲染）。 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from '@/components'
import { libraryApi } from './api'
import type { LibFile, LibProject, LibZone, TreeResponse } from './types'

/** F-G3 类型过滤五档（原型 tabs 顺序） */
export const KIND_TABS: { key: string; label: string }[] = [
  { key: '', label: '全部' },
  { key: 'image', label: '图片' },
  { key: 'video', label: '视频' },
  { key: 'audio', label: '音频' },
  { key: 'doc', label: '文档' },
]

export type ViewMode = 'grid' | 'list'

export type Loc = { project: string; zone: LibZone; sub: string }

export function useLibrary() {
  const [projects, setProjects] = useState<LibProject[]>([])
  const [loc, setLoc] = useState<Loc>({ project: '', zone: '成品', sub: '' })
  const [kind, setKind] = useState('')
  const [q, setQ] = useState('')
  const [qDraft, setQDraft] = useState('')
  const [view, setView] = useState<ViewMode>('grid')
  const [tree, setTree] = useState<TreeResponse | null>(null)
  const [files, setFiles] = useState<LibFile[]>([])
  const [selected, setSelected] = useState<LibFile | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const reqId = useRef(0)

  const loadProjects = useCallback(async (): Promise<LibProject[]> => {
    try {
      const res = await libraryApi.projects()
      setProjects(res.projects)
      return res.projects
    } catch (e) {
      setError(e instanceof Error ? e.message : '读不到项目列表')
      return []
    }
  }, [])

  // 首屏：拉项目并默认选第一个（SPEC-05 §6 #1）
  useEffect(() => {
    void loadProjects().then((list) => {
      setLoc((cur) => (cur.project ? cur : { project: list[0]?.name ?? '', zone: '成品', sub: '' }))
    })
  }, [loadProjects])

  // 搜索防抖：避免每敲一个字打一次后端
  useEffect(() => {
    const t = setTimeout(() => setQ(qDraft.trim()), 250)
    return () => clearTimeout(t)
  }, [qDraft])

  const loadAll = useCallback(async () => {
    if (!loc.project) {
      setTree(null)
      setFiles([])
      return
    }
    const id = ++reqId.current
    setLoading(true)
    setError(null)
    try {
      const [t, f] = await Promise.all([
        libraryApi.tree(loc.project, loc.zone, loc.sub),
        libraryApi.files(loc.project, { zone: loc.zone, kind, q }),
      ])
      if (id !== reqId.current) return // 已有更新的请求，丢弃这次结果
      setTree(t)
      setFiles(f.files)
      // 孤儿索引：文件被手动删了，扫描时已自动剔除，UI 要说出来（不许静默）
      const dropped = t.orphan_removed + f.orphan_removed
      if (dropped > 0) {
        toast.warn(`已自动剔除 ${dropped} 条失效索引（对应文件已不在磁盘上），详见后端日志`)
      }
      setSelected((cur) => (cur && f.files.some((x) => x.path === cur.path) ? cur : null))
    } catch (e) {
      if (id !== reqId.current) return
      setTree(null)
      setFiles([])
      setError(e instanceof Error ? e.message : '读取失败')
    } finally {
      if (id === reqId.current) setLoading(false)
    }
  }, [loc.project, loc.zone, loc.sub, kind, q])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  const goProject = useCallback((project: string) => {
    setLoc({ project, zone: '成品', sub: '' })
    setSelected(null)
  }, [])

  const goZone = useCallback((zone: LibZone) => {
    setLoc((cur) => ({ ...cur, zone, sub: '' }))
    setSelected(null)
  }, [])

  const goSub = useCallback((path: string) => {
    // 面包屑/子目录点击：sub 是 zone 之下的相对路径
    const parts = path.split('/')
    const zone = (parts[1] || '成品') as LibZone
    setLoc((cur) => ({ project: parts[0] ?? cur.project, zone, sub: parts.slice(2).join('/') }))
    setSelected(null)
  }, [])

  const goCrumb = useCallback(
    (i: number) => {
      const c = tree?.breadcrumb[i]
      if (!c) return
      setLoc({ project: c.project, zone: (c.zone || '成品') as LibZone, sub: c.sub })
      setSelected(null)
    },
    [tree],
  )

  const refresh = useCallback(async () => {
    await loadProjects()
    await loadAll()
  }, [loadAll, loadProjects])

  const createProject = useCallback(
    async (name: string) => {
      const res = await libraryApi.createProject(name)
      await loadProjects()
      goProject(res.name)
      toast.ok(`项目 ${res.name} 已建好`)
      return res.name
    },
    [goProject, loadProjects],
  )

  const title = useMemo(() => {
    if (!loc.project) return '内容库'
    return [loc.project, loc.zone, loc.sub].filter(Boolean).join(' / ')
  }, [loc])

  return {
    projects,
    loc,
    kind,
    setKind,
    q,
    qDraft,
    setQDraft,
    view,
    setView,
    tree,
    files,
    selected,
    setSelected,
    loading,
    error,
    title,
    goProject,
    goZone,
    goSub,
    goCrumb,
    refresh,
    createProject,
  }
}

export type LibraryState = ReturnType<typeof useLibrary>
