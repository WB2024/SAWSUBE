import { Routes, Route } from 'react-router-dom'
import { useEffect } from 'react'
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

export default function App() {
  useEffect(() => { wsClient.connect() }, [])
  return (
    <ToastProvider>
      <div className="flex h-full">
        <Sidebar />
        <main className="flex-1 overflow-auto p-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/library" element={<Library />} />
            <Route path="/tv" element={<TVControl />} />
            <Route path="/discover" element={<Discover />} />
            <Route path="/sources" element={<Sources />} />
            <Route path="/schedules" element={<Schedules />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </ToastProvider>
  )
}
