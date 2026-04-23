import { NavLink } from 'react-router-dom'
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
] as const

export function Sidebar() {
  const [tvs, setTvs] = useState<TV[]>([])
  const [statuses, setStatuses] = useState<Record<number, TVStatus>>({})
  const { dark, toggle } = useToggleTheme()

  const refresh = async () => {
    try {
      const list = await api.get<TV[]>('/api/tvs')
      setTvs(list)
      const ss: Record<number, TVStatus> = {}
      for (const t of list) {
        try { ss[t.id] = await api.get<TVStatus>(`/api/tvs/${t.id}/status`) } catch {}
      }
      setStatuses(ss)
    } catch {}
  }
  useEffect(() => { refresh() }, [])
  useWS((m) => {
    if (m.type === 'tv_status') setStatuses((s) => ({ ...s, [m.tv_id]: { ...s[m.tv_id], ...m.payload, id: m.tv_id } }))
  })

  return (
    <aside style={{ background: '#0F1923', width: '240px' }} className="shrink-0 h-full flex flex-col">
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
