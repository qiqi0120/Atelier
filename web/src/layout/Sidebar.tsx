import { NavLink } from 'react-router-dom'
import { NAV_GROUPS } from './NavGroups'
import { ProfileSwitcher } from './ProfileSwitcher'

/** 侧边栏：236px；≤900px 收成 60px 只显图标（UI-SPEC §3 / SPEC-07 §6） */
export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M12 3 3 8l9 5 9-5-9-5Z" />
            <path d="m3 16 9 5 9-5" />
            <path d="m3 12 9 5 9-5" />
          </svg>
        </div>
        <div className="brand-name">Atelier</div>
        <div className="brand-ver">v0.1</div>
      </div>

      <nav className="side-scroll" aria-label="主导航">
        {NAV_GROUPS.map((g, gi) => (
          <div className="nav-group" key={g.label ?? `g${gi}`}>
            {g.label ? <div className="nav-label">{g.label}</div> : null}
            {g.items.map((it) => (
              <NavLink
                key={it.to}
                to={it.to}
                end={it.to === '/'}
                className={({ isActive }) => `nav-item ${isActive ? 'on' : ''}`}
                title={it.label}
              >
                <it.icon size={16} strokeWidth={1.9} aria-hidden />
                <span>{it.label}</span>
                {it.count != null ? <span className="cnt">{it.count}</span> : null}
                {it.dot ? <span className="dot" title="有待处理项" /> : null}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="side-foot">
        <ProfileSwitcher />
      </div>
    </aside>
  )
}

export default Sidebar
