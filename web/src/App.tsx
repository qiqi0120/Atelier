import { Suspense, lazy, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { EmptyState, ToastHost, toast } from '@/components'
import { setToastSink } from '@/lib/api'
import { Sidebar } from '@/layout/Sidebar'
import { Topbar } from '@/layout/Topbar'
import { Skeleton } from '@/components/Skeleton'

/* M1 域：本批实现 */
import { WorkbenchPage } from '@/features/workbench'
import { CapabilityPage } from '@/features/capability'
import { SkillsPage } from '@/features/skills'
import { SettingsPage } from '@/features/settings'

/* M2 域：占位页（SPEC-07 §2） */
import { HotPage } from '@/features/hot'
import { TopicsPage } from '@/features/topics'
import { CalendarPage } from '@/features/calendar'
import { AccountsPage } from '@/features/accounts'
import { AnalyticsPage } from '@/features/analytics'

/* Wave 2 域：占位页，后续整体替换各域目录 */
const ChatPage = lazy(() => import('@/features/chat').then((m) => ({ default: m.ChatPage })))
const LibraryPage = lazy(() => import('@/features/library').then((m) => ({ default: m.LibraryPage })))
const PublishPage = lazy(() => import('@/features/publish').then((m) => ({ default: m.PublishPage })))
const ProfilePage = lazy(() => import('@/features/profile').then((m) => ({ default: m.ProfilePage })))

function ViewFallback() {
  return (
    <div className="view-pad stack" style={{ gap: 12 }}>
      <Skeleton height={22} width={220} />
      <Skeleton height={86} radius={14} />
      <Skeleton height={180} radius={14} />
    </div>
  )
}

function NotFound() {
  return (
    <div className="view-pad">
      <div className="card card-b">
        <EmptyState
          title="这个页面不存在"
          description="13 个页面的入口都在左侧导航里。当前地址可能拼错了，或者功能还没排到这一批。"
          action={
            <a className="btn pri" href="/">
              <span className="btn-txt">回工作台</span>
            </a>
          }
        />
      </div>
    </div>
  )
}

function Shell() {
  const location = useLocation()
  // 对话页是全宽分栏（UI-SPEC §3），其余页面走 .view-pad
  const full = location.pathname === '/chat'
  useEffect(() => {
    setToastSink((message, kind) =>
      kind === 'error'
        ? toast.error(message)
        : kind === 'warn'
          ? toast.warn(message)
          : kind === 'ok'
            ? toast.ok(message)
            : toast.info(message),
    )
    return () => setToastSink(null)
  }, [])

  return (
    <div className="app">
      <Sidebar />
      <div className="main">
        <Topbar />
        <div className="views">
          <div className={`view ${full ? 'full' : ''} on`} key={location.pathname}>
            <Suspense fallback={<ViewFallback />}>
              <Routes location={location}>
                <Route path="/" element={<WorkbenchPage />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/capability" element={<CapabilityPage />} />
                <Route path="/skills" element={<SkillsPage />} />
                <Route path="/hot" element={<HotPage />} />
                <Route path="/topics" element={<TopicsPage />} />
                <Route path="/calendar" element={<CalendarPage />} />
                <Route path="/library" element={<LibraryPage />} />
                <Route path="/publish" element={<PublishPage />} />
                <Route path="/accounts" element={<AccountsPage />} />
                <Route path="/analytics" element={<AnalyticsPage />} />
                <Route path="/profile" element={<ProfilePage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/index.html" element={<Navigate to="/" replace />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          </div>
        </div>
      </div>
      <ToastHost />
    </div>
  )
}

/** 外壳（不含 Router），测试里包 MemoryRouter 复用 */
export function AppShell() {
  return <Shell />
}

export function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  )
}

export default App
