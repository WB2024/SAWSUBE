import { Routes, Route } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { wsClient } from './lib/ws'
import { Sidebar } from './components/Sidebar'
import { ToastProvider } from './components/Toast'
import Dashboard from './pages/Dashboard'
import Library from './pages/Library'
import TVControl from './pages/TVControl'
import Discover from './pages/Discover'
import Sources from './pages/Sources'
import Schedules from './pages/Schedules'
import Settings from './pages/Settings'
import TizenBrew from './pages/TizenBrew'

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  useEffect(() => { wsClient.connect() }, [])
  return (
    <ToastProvider>
      <div className="flex h-full">
        <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        {/* Mobile backdrop */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 bg-black/50 z-40 md:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}
        <div className="flex-1 flex flex-col overflow-hidden min-w-0">
          {/* Mobile-only top bar with hamburger */}
          <div
            className="flex items-center gap-3 px-4 py-3 shrink-0 md:hidden"
            style={{ background: '#0F1923', borderBottom: '1px solid #1E2A35' }}
          >
            <button
              aria-label="Open menu"
              onClick={() => setSidebarOpen(true)}
              style={{ color: '#F4F1ED', background: 'none', border: 'none', cursor: 'pointer', fontSize: '20px', lineHeight: 1, padding: '2px 4px' }}
            >☰</button>
            <span style={{ color: '#C8612A', fontFamily: 'var(--font-display)', fontSize: '16px', letterSpacing: '0.05em' }}>SAWSUBE</span>
          </div>
          <main className="flex-1 overflow-auto p-3 md:p-6">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/library" element={<Library />} />
              <Route path="/tv" element={<TVControl />} />
              <Route path="/discover" element={<Discover />} />
              <Route path="/sources" element={<Sources />} />
              <Route path="/schedules" element={<Schedules />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/tizenbrew" element={<TizenBrew />} />
            </Routes>
          </main>
        </div>
      </div>
    </ToastProvider>
  )
}
