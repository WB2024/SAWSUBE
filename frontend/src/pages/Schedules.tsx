import { useEffect, useState } from 'react'
import { api, Schedule, TV } from '../lib/api'
import { useToast } from '../components/Toast'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const PRESETS = [15, 60, 180, 360, 720, 1440]

export default function Schedules() {
  const [items, setItems] = useState<Schedule[]>([])
  const [tvs, setTvs] = useState<TV[]>([])
  const [editing, setEditing] = useState<Partial<Schedule> | null>(null)
  const t = useToast()

  const load = async () => {
    setItems(await api.get<Schedule[]>('/api/schedules'))
    setTvs(await api.get<TV[]>('/api/tvs'))
  }
  useEffect(() => { document.title = 'SAWSUBE — Schedules'; load() }, [])

  const save = async () => {
    if (!editing) return
    const payload: any = {
      tv_id: editing.tv_id,
      name: editing.name || 'Schedule',
      mode: editing.mode || 'random',
      source_filter: editing.source_filter || {},
      interval_mins: editing.interval_mins || 60,
      time_from: editing.time_from || null,
      time_to: editing.time_to || null,
      days_of_week: editing.days_of_week || '0,1,2,3,4,5,6',
      is_active: editing.is_active !== false,
    }
    try {
      if (editing.id) await api.put(`/api/schedules/${editing.id}`, payload)
      else await api.post('/api/schedules', payload)
      t.push({ type: 'success', text: 'Saved' })
      setEditing(null); load()
    } catch (e: any) { t.push({ type: 'error', text: e.message }) }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl">Schedules</h1>
        <button className="btn-primary" disabled={!tvs.length}
                onClick={() => setEditing({ tv_id: tvs[0]?.id, name: 'New', mode: 'random', interval_mins: 60, days_of_week: '0,1,2,3,4,5,6', is_active: true })}>
          New schedule
        </button>
      </div>

      <div className="space-y-2">
        {items.map((s) => {
          const tv = tvs.find((x) => x.id === s.tv_id)
          return (
            <div key={s.id} className="card p-3 flex justify-between items-center">
              <div className="text-sm">
                <div className="font-semibold">{s.name} <span className={`badge ml-2 ${s.is_active ? 'border-green-600' : 'border-muted'}`}>{s.is_active ? 'active' : 'paused'}</span></div>
                <div className="text-muted text-xs">{tv?.name || `TV ${s.tv_id}`} · {s.mode} · every {s.interval_mins}m · days {s.days_of_week}</div>
              </div>
              <div className="flex gap-2">
                <button className="btn-ghost" onClick={() => api.post(`/api/schedules/${s.id}/trigger`).then(() => t.push({ type: 'info', text: 'Triggered' }))}>Run now</button>
                <button className="btn-ghost" onClick={() => api.post(`/api/schedules/${s.id}/toggle`).then(load)}>{s.is_active ? 'Pause' : 'Activate'}</button>
                <button className="btn-ghost" onClick={() => setEditing(s)}>Edit</button>
                <button className="btn-danger" onClick={() => confirm('Delete schedule?') && api.del(`/api/schedules/${s.id}`).then(load)}>Del</button>
              </div>
            </div>
          )
        })}
        {items.length === 0 && <div className="card p-6 text-muted">No schedules yet.</div>}
      </div>

      {editing && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center p-4 z-40" onClick={() => setEditing(null)}>
          <div className="card p-6 w-full max-w-lg space-y-3" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-xl font-bold">{editing.id ? 'Edit' : 'New'} schedule</h2>
            <Field label="Name"><input className="input" value={editing.name || ''} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></Field>
            <Field label="TV">
              <select className="input" value={editing.tv_id || ''} onChange={(e) => setEditing({ ...editing, tv_id: Number(e.target.value) })}>
                {tvs.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </Field>
            <Field label="Mode">
              <select className="input" value={editing.mode || 'random'} onChange={(e) => setEditing({ ...editing, mode: e.target.value })}>
                <option>random</option><option>sequential</option><option>weighted</option>
              </select>
            </Field>
            <Field label="Interval (mins)">
              <div className="flex gap-2 items-center">
                <input type="number" min={1} className="input w-24" value={editing.interval_mins || 60} onChange={(e) => setEditing({ ...editing, interval_mins: Number(e.target.value) })} />
                {PRESETS.map((p) => <button key={p} type="button" className="btn-ghost text-xs" onClick={() => setEditing({ ...editing, interval_mins: p })}>{p < 60 ? p + 'm' : p / 60 + 'h'}</button>)}
              </div>
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="From"><input type="time" className="input" value={editing.time_from || ''} onChange={(e) => setEditing({ ...editing, time_from: e.target.value || null })} /></Field>
              <Field label="To"><input type="time" className="input" value={editing.time_to || ''} onChange={(e) => setEditing({ ...editing, time_to: e.target.value || null })} /></Field>
            </div>
            <Field label="Days">
              <div className="flex gap-1">
                {DAYS.map((d, i) => {
                  const arr = (editing.days_of_week || '').split(',').filter(Boolean)
                  const on = arr.includes(String(i))
                  return (
                    <button key={d} type="button" className={on ? 'btn-primary text-xs' : 'btn-ghost text-xs'}
                            onClick={() => {
                              const set = new Set(arr)
                              on ? set.delete(String(i)) : set.add(String(i))
                              setEditing({ ...editing, days_of_week: Array.from(set).sort().join(',') })
                            }}>{d}</button>
                  )
                })}
              </div>
            </Field>
            <Field label="Source filter (JSON)">
              <textarea className="input font-mono text-xs h-24" value={JSON.stringify(editing.source_filter || {}, null, 2)}
                        onChange={(e) => { try { setEditing({ ...editing, source_filter: JSON.parse(e.target.value) }) } catch {} }} />
            </Field>
            <div className="flex gap-2 justify-end">
              <button className="btn-ghost" onClick={() => setEditing(null)}>Cancel</button>
              <button className="btn-primary" onClick={save}>Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Field({ label, children }: any) {
  return <label className="block"><div className="text-xs text-muted mb-1">{label}</div>{children}</label>
}
