import { useEffect, useState, createContext, useContext, ReactNode, useCallback } from 'react'
import { useWS } from '../lib/hooks'

type Toast = { id: number; type: 'info' | 'success' | 'error'; text: string }
const Ctx = createContext<{ push: (t: Omit<Toast, 'id'>) => void }>({ push: () => {} })
export const useToast = () => useContext(Ctx)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const push = useCallback((t: Omit<Toast, 'id'>) => {
    const id = Date.now() + Math.random()
    setItems((s) => [...s, { ...t, id }])
    setTimeout(() => setItems((s) => s.filter((x) => x.id !== id)), 4000)
  }, [])
  useWS((m) => {
    if (m.type === 'schedule_fired') push({ type: 'info', text: `Schedule fired (TV ${m.tv_id})` })
    else if (m.type === 'art_changed') push({ type: 'success', text: `Art changed on TV ${m.tv_id}` })
    else if (m.type === 'image_added') push({ type: 'info', text: `Image added: ${m.filename}` })
    else if (m.type === 'tv_status' && m.payload?.online === false) push({ type: 'error', text: `TV ${m.tv_id} offline` })
  })
  return (
    <Ctx.Provider value={{ push }}>
      {children}
      <div className="fixed bottom-4 right-4 flex flex-col gap-2 z-50">
        {items.map((t) => (
          <div key={t.id} style={{
            background: '#0F1923',
            color: '#F4F1ED',
            borderRadius: '6px',
            padding: '10px 16px',
            fontSize: '14px',
            fontFamily: 'var(--font-body)',
            borderLeft: `4px solid ${t.type === 'error' ? '#A33228' : t.type === 'success' ? '#C8612A' : '#C49A3C'}`,
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            minWidth: '220px',
          }}>
            {t.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}
