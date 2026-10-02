import { useCallback, useEffect, useMemo, useState } from 'react'
import { Download, X } from 'lucide-react'
import { Button, Card, Chip, EmptyState, Tabs, toast } from '@/components'
import { PageHead } from '@/features/shared/PageHead'
import { useAtelier } from '@/lib/store'
import { DIM_HINTS, DIM_KEYS, DIM_NAMES, parseRedlines, profileApi, redlinesToMarkdown } from './api'
import type { DimKey, PreviewResult, ProfileBrief, ProfileDetail } from './api'
import { DimNav } from './DimNav'
import { GeneralModeToggle, generalModeToast } from './GeneralModeToggle'
import { MemoryPanel } from './MemoryPanel'
import { ProfileEditor, savedToast } from './ProfileEditor'
import { ProfileWizard } from './ProfileWizard'

const EMPTY_SCORES: Record<string, number> = Object.fromEntries(DIM_KEYS.map((k) => [k, 0]))

/** 把详情压成侧栏切换器需要的摘要（lib/store 的 ActiveProfile 形状） */
function toActive(p: ProfileDetail | ProfileBrief) {
  return {
    id: p.id,
    name: p.name,
    platforms: p.platforms,
    generalMode: p.general_mode,
    completeness: p.completeness_overall,
  }
}

export function ProfilePage() {
  const [briefs, setBriefs] = useState<ProfileBrief[]>([])
  const [current, setCurrent] = useState<ProfileDetail | null>(null)
  const [dim, setDim] = useState<DimKey>('identity')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const [wizardSeed, setWizardSeed] = useState<{ profile: ProfileDetail; token: string } | null>(null)

  // 侧边栏切换器与本页双向同步（UI-SPEC §5）：本页是数据源，切到它写的 store
  const setProfile = useAtelier((s) => s.setProfile)
  const setProfiles = useAtelier((s) => s.setProfiles)
  const setMemories = useAtelier((s) => s.setMemories)

  const refreshList = useCallback(async () => {
    const { profiles } = await profileApi.list()
    setBriefs(profiles)
    setProfiles(profiles.map(toActive))
    return profiles
  }, [setProfiles])

  const openProfile = useCallback(
    async (id: string) => {
      const detail = await profileApi.detail(id)
      setCurrent(detail)
      setDrafts({})
      setProfile(toActive(detail))
      setMemories(detail.memories)
      return detail
    },
    [setMemories, setProfile],
  )

  useEffect(() => {
    let alive = true
    void (async () => {
      setLoading(true)
      try {
        const profiles = await refreshList()
        if (!alive) return
        if (profiles.length === 0) {
          setCurrent(null)
          setProfile(null)
          return
        }
        await openProfile(profiles[0].id)
      } catch {
        /* lib/api 已 toast */
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [openProfile, refreshList, setProfile])

  // 编辑中的草稿：切维度不丢内容，保存才落库
  const value = useMemo(() => {
    if (!current) return ''
    const key = dim
    if (key in drafts) return drafts[key]
    if (key === 'memories') return current.preferences // 只作兜底，记忆走独立面板
    return current[key]
  }, [current, dim, drafts])

  const dirty = useMemo(() => {
    if (!current || dim === 'memories') return false
    return value !== current[dim]
  }, [current, dim, value])

  const setValue = (next: string) => setDrafts((d) => ({ ...d, [dim]: next }))

  const save = async () => {
    if (!current || dim === 'memories' || !dirty) return
    setSaving(true)
    try {
      const updated = await profileApi.patch(current.id, { [dim]: value })
      setCurrent(updated)
      setDrafts((d) => {
        const next = { ...d }
        delete next[dim]
        return next
      })
      setProfile(toActive(updated))
      void refreshList()
      savedToast()
    } finally {
      setSaving(false)
    }
  }

  const addMemory = async (text: string): Promise<void> => {
    if (!current) return
    await profileApi.addMemory(current.id, text)
    const detail = await profileApi.detail(current.id)
    setCurrent(detail)
    setMemories(detail.memories)
    void refreshList()
  }

  const deleteMemory = async (memoryId: string) => {
    if (!current) return
    await profileApi.deleteMemory(current.id, memoryId)
    const detail = await profileApi.detail(current.id)
    setCurrent(detail)
    setMemories(detail.memories)
    toast.ok('已删除，下一轮起不再注入')
  }

  const toggleGeneral = async (enabled: boolean) => {
    if (!current) return
    const res = await profileApi.generalMode(current.id, enabled)
    setCurrent(res)
    setProfile(toActive(res))
    void refreshList()
    generalModeToast(enabled)
  }

  const removeRedline = async (item: string) => {
    if (!current) return
    const items = parseRedlines(current.preferences).filter((x) => x !== item)
    const updated = await profileApi.patch(current.id, { preferences: redlinesToMarkdown(items, current.preferences) })
    setCurrent(updated)
    toast.ok('已删除这条红线')
  }

  const startWizard = async () => {
    try {
      const created = await profileApi.create({ name: '新账号', platforms: [] })
      await refreshList()
      setWizardSeed({ profile: created, token: created.wizard_token })
    } catch {
      /* lib/api 已 toast */
    }
  }

  const onWizardDone = (profile: ProfileDetail) => {
    setCurrent(profile)
    setWizardSeed(null)
    void refreshList()
    setProfile(toActive(profile))
    setDim('identity')
  }

  const onWizardAbandon = (profile: ProfileDetail) => {
    setCurrent(profile)
    setWizardSeed(null)
    void refreshList()
    setProfile(toActive(profile))
    toast.info('已保留填过的内容，随时可以继续改')
  }

  const exportMd = () => {
    if (!current) return
    // 走同源下载：走 api client 会被读成 JSON，导出是纯文本文件
    window.open(`/api/profiles/${encodeURIComponent(current.id)}/export`, '_blank')
  }

  const redlines = current ? parseRedlines(current.preferences) : []

  return (
    <div className="view-pad">
      <PageHead
        title="账号画像"
        desc="六维画像是所有 AI 产出的地基。以消息前缀内联，不落全局文件，两个画像不会互相污染。"
        actions={
          <>
            <Tabs
              items={[
                ...briefs.map((b) => ({ key: b.id, label: b.name })),
                { key: '__new', label: '＋ 新建' },
              ]}
              value={current?.id ?? '__new'}
              onChange={(key) => (key === '__new' ? void startWizard() : void openProfile(key))}
              ariaLabel="画像切换"
            />
            <Button icon={Download} disabled={!current} onClick={exportMd}>
              导出
            </Button>
          </>
        }
      />

      {briefs.length === 0 && !loading ? (
        <Card>
          <EmptyState
            title="还没有画像"
            description="建一个之后，AI 产出的语气、平台约束、禁忌话题会立刻按它来走。也可以先不建——通用模式照样能干活。"
            actionLabel="用 4 步向导建一个"
            onAction={() => void startWizard()}
          />
        </Card>
      ) : null}

      {current ? (
        <div className="dims">
          <DimNav
            scores={current.completeness ?? EMPTY_SCORES}
            overall={current.completeness_overall ?? 0}
            value={dim}
            onChange={setDim}
          />

          <div className="stack">
            <ProfileEditor
              dim={dim}
              title={DIM_NAMES[dim]}
              hint={DIM_HINTS[dim]}
              value={value}
              dirty={dirty}
              saving={saving}
              generalMode={current.general_mode}
              onChange={setValue}
              onSave={() => void save()}
              onPreview={async (): Promise<PreviewResult> => profileApi.preview(current.id)}
            />

            {dim === 'preferences' ? (
              <Card
                title="偏好红线"
                actions={
                  <span className="help">逐条删掉不要的；在上面编辑器里可整体改写</span>
                }
                tight
              >
                {redlines.length === 0 ? (
                  <div className="help" style={{ padding: '10px 14px' }}>
                    还没有拆出红线条目。在编辑器里每行写一条「- xxx」就会出现在这里。
                  </div>
                ) : (
                  redlines.map((r) => (
                    <div className="redline" key={r}>
                      <span>{r}</span>
                      <span className="mut2" style={{ fontSize: 11 }}>
                        软提醒 · 不阻断
                      </span>
                      <button
                        type="button"
                        className="iconbtn"
                        aria-label={`删除红线：${r}`}
                        onClick={() => void removeRedline(r)}
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ))
                )}
              </Card>
            ) : null}

            <MemoryPanel memories={current.memories} onAdd={addMemory} onDelete={deleteMemory} />

            <GeneralModeToggle
              enabled={current.general_mode}
              profileName={current.name}
              onToggle={toggleGeneral}
            />

            <div className="row" style={{ gap: 8 }}>
              <Chip tone="outline" mono>
                {current.md_path}
              </Chip>
              <span className="help">
                这份 md 就是落盘的那份，可以直接手改；改完把 updated_at 调新，重启会自动导回。
              </span>
            </div>
          </div>
        </div>
      ) : null}

      <ProfileWizard
        open={wizardSeed !== null}
        created={wizardSeed}
        onDone={onWizardDone}
        onAbandon={onWizardAbandon}
        onClose={() => setWizardSeed(null)}
      />
    </div>
  )
}

export default ProfilePage
