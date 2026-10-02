import { useLocation, useNavigate } from 'react-router-dom'
import { Activity, Plus } from 'lucide-react'
import { Button, Tabs, toast } from '@/components'
import { PAGE_TITLES, TOP_TABS } from './NavGroups'

/** 顶栏 56px：面包屑 / 视图切换 / 体检 / 新会话（UI-SPEC §3） */
export function Topbar() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const title = PAGE_TITLES[pathname] ?? 'Atelier'
  const showTabs = TOP_TABS.some((t) => t.to === pathname)

  return (
    <header className="topbar">
      <div className="crumb">
        <b>{title}</b>
      </div>
      <div className="top-right">
        {showTabs ? (
          <Tabs
            ariaLabel="视图切换"
            items={TOP_TABS.map((t) => ({ key: t.to, label: t.label }))}
            value={pathname}
            onChange={(k) => navigate(k)}
          />
        ) : null}
        <Button size="sm" variant="ghost" onClick={() => navigate('/settings')} title="环境体检">
          <Activity size={14} />
          <span className="hide-xs" style={{ fontSize: 12 }}>
            体检
          </span>
        </Button>
        <Button
          size="sm"
          variant="primary"
          icon={Plus}
          onClick={() => {
            navigate('/chat')
            toast('已开新会话 · 画像已注入', 'ok')
          }}
        >
          新会话
        </Button>
      </div>
    </header>
  )
}

export default Topbar
