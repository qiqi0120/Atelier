import {
  LayoutDashboard,
  MessageCircle,
  Flame,
  Blocks,
  ListChecks,
  Calendar,
  Folder,
  Send,
  User,
  ChartColumn,
  Cpu,
  UserCircle,
  SlidersHorizontal,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export type NavItem = {
  to: string
  label: string
  icon: LucideIcon
  /** 右侧计数（会话数 / 收藏数） */
  count?: number
  /** 右侧状态点：有未完成发布 / 有待配置 */
  dot?: boolean
}

export type NavGroup = {
  /** 第一组（工作台）无标题，与原型一致 */
  label?: string
  items: NavItem[]
}

/** 侧边栏分组：工作台 / 输入 / 策划 / 发布 / 系统（UI-SPEC §3） */
export const NAV_GROUPS: NavGroup[] = [
  {
    items: [
      { to: '/', label: '工作台', icon: LayoutDashboard },
      { to: '/chat', label: '对话工作台', icon: MessageCircle, count: 6 },
    ],
  },
  {
    label: '输入',
    items: [
      { to: '/hot', label: '热点发现', icon: Flame, count: 7 },
      { to: '/capability', label: '能力地图', icon: Blocks },
    ],
  },
  {
    label: '策划',
    items: [
      { to: '/topics', label: '选题库', icon: ListChecks, count: 12 },
      { to: '/calendar', label: '内容日历', icon: Calendar },
      { to: '/library', label: '内容库', icon: Folder },
    ],
  },
  {
    label: '发布',
    items: [
      { to: '/publish', label: '发布中心', icon: Send, dot: true },
      { to: '/accounts', label: '账号登录', icon: User },
      { to: '/analytics', label: '数据复盘', icon: ChartColumn },
    ],
  },
  {
    label: '系统',
    items: [
      { to: '/skills', label: '技能库', icon: Cpu },
      { to: '/profile', label: '账号画像', icon: UserCircle },
      { to: '/settings', label: '设置', icon: SlidersHorizontal, dot: true },
    ],
  },
]

/** 顶栏面包屑 / 页面标题（UI-SPEC §6 页面清单） */
export const PAGE_TITLES: Record<string, string> = {
  '/': '工作台',
  '/chat': '对话工作台',
  '/hot': '热点发现',
  '/capability': '能力地图',
  '/topics': '选题库',
  '/calendar': '内容日历',
  '/library': '内容库',
  '/publish': '发布中心',
  '/accounts': '账号登录',
  '/analytics': '数据复盘',
  '/profile': '账号画像',
  '/skills': '技能库',
  '/settings': '设置',
}

/** 顶栏视图切换只在对话 / 能力地图 / 技能库 三个页面出现（与原型一致） */
export const TOP_TABS: { to: string; label: string }[] = [
  { to: '/chat', label: '对话' },
  { to: '/capability', label: '能力地图' },
  { to: '/skills', label: '技能库' },
]
