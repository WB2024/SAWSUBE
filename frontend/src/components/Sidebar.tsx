import { NavLink, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api, TV, TVStatus } from '../lib/api'
import { useWS, useToggleTheme } from '../lib/hooks'

const links = [
  ['/', 'Dashboard'],
  ['/library', 'Library'],
  ['/tv', 'TV Control'],
  ['/discover', 'Discover'],
  ['/sources', 'Sources'],
  ['/schedules', 'Schedules'],
  ['/settings', 'Settings'],
  ['/tizenbrew', 'TizenBrew'],
] as const

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [tvs, setTvs] = useState<TV[]>([])
  const [statuses, setStatuses] = useState<Record<number, TVStatus>>({})
  const { dark, toggle } = useToggleTheme()
  const location = useLocation()

  // Close drawer on navigation (mobile)
  useEffect(() => { onClose() }, [location.pathname])

  const refresh = async () => {
    try {
      const list = await api.get<TV[]>('/api/tvs')
      setTvs(list)
      const results = await Promise.all(
        list.map((t) => api.get<TVStatus>(`/api/tvs/${t.id}/status`).catch(() => null)),
      )
      const ss: Record<number, TVStatus> = {}
      list.forEach((t, i) => { if (results[i]) ss[t.id] = results[i] as TVStatus })
      setStatuses(ss)
    } catch {
      /* ignore */
    }
  }
  useEffect(() => { refresh() }, [])
  useWS((m) => {
    if (m.type === 'tv_status') setStatuses((s) => ({ ...s, [m.tv_id]: { ...s[m.tv_id], ...m.payload, id: m.tv_id } }))
  })

  return (
    <aside
      style={{ background: '#0F1923', width: '240px' }}
      className={[
        'shrink-0 h-full flex flex-col overflow-y-auto',
        // Mobile: fixed overlay drawer, slides in/out
        'fixed inset-y-0 left-0 z-50 transition-transform duration-200',
        open ? 'translate-x-0' : '-translate-x-full',
        // Desktop: back in normal flow
        'md:static md:translate-x-0 md:z-auto',
      ].join(' ')}
    >
      {/* Close button — mobile only */}
      <button
        className="md:hidden absolute top-3 right-3"
        onClick={onClose}
        aria-label="Close menu"
        style={{ color: '#A09890', background: 'none', border: 'none', cursor: 'pointer', fontSize: '18px', lineHeight: 1, padding: '4px' }}
      >✕</button>
      {/* Logo block — Canvas background matches logo's own background for perfect rendering */}
      <div style={{ background: '#F4F1ED', borderBottom: '3px solid #C8612A', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '14px 20px' }}>
        <img src="/Logo.png" alt="SAWSUBE" style={{ height: '38px', width: 'auto', display: 'block' }} />
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-3 flex flex-col gap-1">
        {links.map(([to, label]) => (
          <NavLink key={to} to={to} end={to === '/'}
            className={({ isActive }) => isActive ? 'sawsube-nav-active' : 'sawsube-nav-item'}>
            {label}
          </NavLink>
        ))}
      </nav>

      {/* TV status list */}
      <div style={{ borderTop: '1px solid #1E2A35' }} className="p-3 space-y-2">
        <div style={{ color: '#A09890' }} className="text-xs">TVs</div>
        {tvs.length === 0 && <div style={{ color: '#A09890' }} className="text-xs">None added</div>}
        {tvs.map((t) => {
          const st = statuses[t.id]
          const dotColor = st?.online ? '#4A7C5F' : st ? '#A33228' : '#C49A3C'
          return (
            <div key={t.id} className="flex items-center gap-2 text-sm" style={{ color: '#A09890' }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: dotColor, flexShrink: 0, display: 'inline-block' }} />
              <span className="truncate">{t.name}</span>
            </div>
          )
        })}
        <button className="btn-ghost w-full mt-2" style={{ color: '#A09890', borderColor: '#1E2A35' }} onClick={toggle}>
          {dark ? 'Light mode' : 'Dark mode'}
        </button>
      </div>

      {/* Footer */}
      <div style={{ borderTop: '1px solid #1E2A35', color: '#6B6560', fontSize: '11px', fontFamily: 'var(--font-body)', padding: '10px 20px' }}>
        SAWSUBE · by WB
      </div>
    </aside>
  )
}
