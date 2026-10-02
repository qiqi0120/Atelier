/** SPEC-08 · 选题池状态钩子：加载 / 搜索（客户端过滤）/ CRUD / 状态流转。 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from '@/components'
import { topicsApi } from './api'
import { STATUS_FLOW, type Topic, type TopicStatus } from './types'

export function useTopics() {
  const [items, setItems] = useState<Topic[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [qDraft, setQDraft] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await topicsApi.list()
      setItems(r.items)
      setError('')
    } catch {
      // api 层已 toast；页面里再放一条静态错误说明
      setError('选题列表加载失败，确认服务在跑后点重试')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const refresh = useCallback(() => {
    void load()
  }, [load])

  const filtered = useMemo(() => {
    const q = qDraft.trim().toLowerCase()
    if (!q) return items
    return items.filter(
      (t) => t.title.toLowerCase().includes(q) || t.angle.toLowerCase().includes(q),
    )
  }, [items, qDraft])

  const create = useCallback(
    async (title: string, angle: string) => {
      const t = await topicsApi.create({ title, angle: angle || undefined })
      await load()
      return t
    },
    [load],
  )

  const move = useCallback(
    async (topic: Topic, dir: -1 | 1) => {
      const i = STATUS_FLOW.indexOf(topic.status)
      const next = STATUS_FLOW[i + dir]
      if (!next) return
      try {
        await topicsApi.update(topic.id, { status: next })
        await load()
      } catch {
        /* api 层已 toast */
      }
    },
    [load],
  )

  const remove = useCallback(
    async (id: string) => {
      try {
        await topicsApi.remove(id)
        toast.ok('选题已删除')
        await load()
      } catch {
        /* api 层已 toast */
      }
    },
    [load],
  )

  /** F-E4 排期：设置 / 清空（空串）建议发布日（SPEC-10 §3）。 */
  const schedule = useCallback(
    async (id: string, dueDate: string) => {
      try {
        await topicsApi.update(id, { due_date: dueDate })
        await load()
      } catch {
        /* api 层已 toast */
      }
    },
    [load],
  )

  const byStatus = useCallback(
    (s: TopicStatus) => filtered.filter((t) => t.status === s),
    [filtered],
  )

  return {
    items: filtered,
    loading,
    error,
    qDraft,
    setQDraft,
    refresh,
    create,
    move,
    remove,
    schedule,
    byStatus,
  }
}
