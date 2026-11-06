import { useEffect, useRef, useState } from 'react'
import { api, TV, TVContent, TVImage, TVStatus } from '../lib/api'
import { useToast } from '../components/Toast'

export default function TVControl() {
  const [tvs, setTvs] = useState<TV[]>([])
  const [active, setActive] = useState<number | null>(null)
  const t = useToast()

  useEffect(() => {
    document.title = 'SAWSUBE — TV Control'
    api.get<TV[]>('/api/tvs').then((list) => {
      setTvs(list)
      if (list[0]) setActive(list[0].id)
    })
  }, [])

  return (
    <div className="space-y-4">
      <h1 className="text-2xl">TV Control</h1>
      <div className="flex gap-2 flex-wrap">
        {tvs.map((tv) => (
          <button key={tv.id} className={active === tv.id ? 'btn-primary' : 'btn-ghost'}
                  onClick={() => setActive(tv.id)}>{tv.name}</button>
        ))}
      </div>
      {active && tvs.find((x) => x.id === active) && <TVPanel tv={tvs.find((x) => x.id === active)!} />}
      {tvs.length === 0 && <div className="card p-6 text-muted">No TVs. Add one in Discover.</div>}
    </div>
  )
}

function TVPanel({ tv }: { tv: TV }) {
  const t = useToast()
  const [status, setStatus] = useState<TVStatus | null>(null)
  const [info, setInfo] = useState<any>(null)
  const [settings, setSettings] = useState<any>({})
  const [mattes, setMattes] = useState<string[]>([])
  const [tvImages, setTVImages] = useState<TVImage[]>([])

  const refresh = async () => {
    try { setStatus(await api.get(`/api/tvs/${tv.id}/status`)) } catch {}
    try { setInfo(await api.get(`/api/tvs/${tv.id}/info`)) } catch {}
    try { setSettings(await api.get(`/api/tvs/${tv.id}/art/settings`)) } catch {}
    try { setMattes(await api.get(`/api/tvs/${tv.id}/art/mattes`)) } catch {}
    try { setTVImages(await api.get(`/api/images/tv/${tv.id}`)) } catch {}
  }
  useEffect(() => { refresh() }, [tv.id])

  const apply = async (patch: any) => {
    const prev = settings
    setSettings({ ...settings, ...patch })
    try {
      await api.post(`/api/tvs/${tv.id}/art/settings`, patch)
      t.push({ type: 'success', text: 'Applied' })
    } catch (e: any) {
      setSettings(prev)
      t.push({ type: 'error', text: e.message })
    }
  }

  const pair = async () => {
    t.push({ type: 'info', text: 'Pairing… press Allow on TV' })
    try {
      const r: any = await api.post(`/api/tvs/${tv.id}/pair`)
      t.push({ type: r.paired ? 'success' : 'error', text: r.paired ? 'Paired' : 'Pair failed' })
      refresh()
    } catch (e: any) { t.push({ type: 'error', text: e.message }) }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div className="card p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <div className="font-semibold">{tv.name}</div>
            <div className="text-xs text-muted">{tv.ip}</div>
          </div>
          <span className={`badge ${status?.online ? 'border-[#4A7C5F] text-[#4A7C5F]' : 'border-[#A33228] text-[#A33228]'}`}>
            {status?.online ? 'Online' : 'Offline'} {status?.paired ? '· paired' : '· not paired'}
          </span>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button className="btn-primary" onClick={pair}>Pair</button>
          <button className="btn-ghost" onClick={() => api.post(`/api/tvs/${tv.id}/power/on`)}>Power On (WoL)</button>
          <button className="btn-ghost" onClick={() => api.post(`/api/tvs/${tv.id}/power/off`)}>Power Off</button>
          <button className="btn-ghost" onClick={() => api.post(`/api/tvs/${tv.id}/artmode/on`)}>Art On</button>
          <button className="btn-ghost" onClick={() => api.post(`/api/tvs/${tv.id}/artmode/off`)}>Art Off</button>
          <button className="btn-ghost" onClick={refresh}>Refresh</button>
        </div>
        <div className="text-xs text-muted">
          Model: {tv.model || info?.device?.modelName || '—'} · MAC: {tv.mac || '—'}<br />
          Firmware: {info?.device?.firmwareVersion || '—'}
        </div>
      </div>

      <div className="card p-4 space-y-3">
        <div className="font-semibold">Art Mode Settings</div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
          <Field label="Brightness (1–10)">
            <input type="number" min={1} max={10} className="input"
                   value={settings.brightness ?? 5}
                   onChange={(e) => setSettings({ ...settings, brightness: Number(e.target.value) })}
                   onBlur={(e) => apply({ brightness: Number(e.target.value) })} />
          </Field>
          <Field label="Color temp (-5..5)">
            <input type="number" min={-5} max={5} className="input"
                   value={settings.color_temp ?? 0}
                   onChange={(e) => setSettings({ ...settings, color_temp: Number(e.target.value) })}
                   onBlur={(e) => apply({ color_temp: Number(e.target.value) })} />
          </Field>
          <Field label="Slideshow interval (mins)">
            <select className="input" value={settings.slideshow_interval ?? 3}
                    onChange={(e) => apply({ slideshow_interval: Number(e.target.value) })}>
              {[3, 5, 10, 15, 30, 60, 180, 360, 720, 1440].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </Field>
          <Field label="Shuffle">
            <input type="checkbox" checked={!!settings.shuffle}
                   onChange={(e) => apply({ shuffle: e.target.checked })} />
          </Field>
          <Field label="Motion timer">
            <select className="input" value={settings.motion_timer ?? 'off'}
                    onChange={(e) => apply({ motion_timer: e.target.value })}>
              {['off', '5', '15', '30', '60', '180'].map((v) => <option key={v}>{v}</option>)}
            </select>
          </Field>
          <Field label="Motion sensitivity (1-3)">
            <input type="number" min={1} max={3} className="input"
                   value={settings.motion_sensitivity ?? 2}
                   onChange={(e) => setSettings({ ...settings, motion_sensitivity: Number(e.target.value) })}
                   onBlur={(e) => apply({ motion_sensitivity: Number(e.target.value) })} />
          </Field>
          <Field label="Brightness sensor">
            <input type="checkbox" checked={!!settings.brightness_sensor}
                   onChange={(e) => apply({ brightness_sensor: e.target.checked })} />
          </Field>
        </div>
      </div>

      <div className="card p-4 col-span-1 lg:col-span-2">
        <div className="font-semibold mb-2">Mattes available ({mattes.length})</div>
        <div className="flex flex-wrap gap-1 max-h-40 overflow-auto">
          {mattes.map((m) => <span key={m} className="badge">{m}</span>)}
          {mattes.length === 0 && <div className="text-muted text-sm">Pair the TV first to load matte list.</div>}
        </div>
      </div>

      <div className="card p-4 col-span-1 lg:col-span-2">
        <div className="font-semibold mb-2">Currently on TV ({tvImages.length})</div>
        <div className="flex gap-2 overflow-x-auto pb-2">
          {tvImages.map((ti) => (
            <div key={ti.id} className="relative group shrink-0 flex flex-col gap-1">
              <div className="relative">
                <img src={`/api/images/tv/${tv.id}/thumbnail/${ti.remote_id}`} alt=""
                     className="w-32 h-20 object-cover rounded border border-border cursor-pointer"
                     onClick={() => api.post(`/api/tvs/${tv.id}/art/current`, { tv_image_id: ti.id })}
                     onError={(e) => ((e.target as HTMLImageElement).src = `/api/images/${ti.image_id}/thumbnail`)} />
                <button className="absolute top-1 right-1 btn-danger text-xs px-1 py-0.5 opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
                        onClick={() => api.del(`/api/images/${ti.image_id}/tv/${tv.id}`).then(refresh)}>×</button>
              </div>
              <select
                className="input text-[10px] py-0 px-1 h-6 w-32"
                value={ti.matte}
                onChange={async (e) => {
                  try {
                    await api.post(`/api/tvs/${tv.id}/art/matte/${ti.id}`, { matte: e.target.value })
                    refresh()
                  } catch {}
                }}
              >
                <option value="none">none</option>
                {mattes.filter(m => m !== 'none').map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
          ))}
          {tvImages.length === 0 && <div className="text-muted text-sm">None on TV yet.</div>}
        </div>
      </div>

      <TVContentPanel tv={tv} onChanged={refresh} />
    </div>
  )
}

const CATEGORIES: { value: string; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'MY-C0002', label: 'My Photos' },
  { value: 'MY-C0004', label: 'Favourites' },
  { value: 'MY-C0008', label: 'Art Store' },
]

function TVContentPanel({ tv, onChanged }: { tv: TV; onChanged: () => void }) {
  const t = useToast()
  const [items, setItems] = useState<TVContent[] | null>(null)
  const [category, setCategory] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // TV queries take seconds; only the latest request may update state, so a slow
  // response for a previous category/TV can't overwrite the current one
  const reqId = useRef(0)
  const load = async (cat = category) => {
    const id = ++reqId.current
    setLoading(true)
    setError(null)
    try {
      const q = cat ? `?category=${encodeURIComponent(cat)}` : ''
      const data = await api.get<TVContent[]>(`/api/tvs/${tv.id}/art/available${q}`)
      if (id === reqId.current) setItems(data)
    } catch (e: any) {
      if (id === reqId.current) {
        setItems(null)
        setError(e.message)
      }
    } finally {
      if (id === reqId.current) setLoading(false)
    }
  }
  useEffect(() => { setItems(null); load() }, [tv.id])

  const show = async (c: TVContent) => {
    try {
      const r: any = await api.post(`/api/tvs/${tv.id}/art/available/${encodeURIComponent(c.content_id)}/show`)
      t.push({ type: r.ok ? 'success' : 'error', text: r.ok ? `Showing ${c.content_id}` : 'TV refused to show image' })
    } catch (e: any) { t.push({ type: 'error', text: e.message }) }
  }

  const remove = async (c: TVContent) => {
    if (!confirm(`Delete ${c.content_id} from the TV? This cannot be undone.`)) return
    try {
      const r: any = await api.del(`/api/tvs/${tv.id}/art/available/${encodeURIComponent(c.content_id)}`)
      if (!r.ok) throw new Error('Delete failed — the TV still lists this image')
      setItems((prev) => prev?.filter((x) => x.content_id !== c.content_id) ?? null)
      if (c.tv_image_id) onChanged()
      t.push({ type: 'success', text: `Deleted ${c.content_id}` })
    } catch (e: any) { t.push({ type: 'error', text: e.message }) }
  }

  const reconcile = async () => {
    try {
      const r: any = await api.post(`/api/tvs/${tv.id}/art/reconcile`)
      t.push({ type: 'success', text: `${r.marked_removed} stale entr${r.marked_removed === 1 ? 'y' : 'ies'} cleaned up` })
      onChanged()
    } catch (e: any) { t.push({ type: 'error', text: e.message }) }
  }

  return (
    <div className="card p-4 col-span-1 lg:col-span-2">
      <div className="flex items-center justify-between gap-2 flex-wrap mb-2">
        <div className="font-semibold">All images stored on the Frame {items ? `(${items.length})` : ''}</div>
        <div className="flex gap-2 items-center">
          <select className="input text-sm py-1" value={category}
                  onChange={(e) => { setCategory(e.target.value); load(e.target.value) }}>
            {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          <button className="btn-ghost" disabled={loading} onClick={() => load()}>
            {loading ? 'Loading…' : 'Reload'}
          </button>
          <button className="btn-ghost" title="Mark SAWSUBE entries that no longer exist on the TV as removed"
                  onClick={reconcile}>Clean up stale</button>
        </div>
      </div>
      {error && <div className="text-sm text-[#A33228]">Could not load from TV: {error}</div>}
      {!error && items && items.length === 0 && <div className="text-muted text-sm">No images in this category.</div>}
      {items && items.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2 max-h-[32rem] overflow-auto">
          {items.map((c) => (
            <div key={c.content_id} className="relative group flex flex-col gap-1">
              <img src={`/api/images/tv/${tv.id}/thumbnail/${encodeURIComponent(c.content_id)}`} alt={c.content_id}
                   loading="lazy"
                   className="w-full aspect-video object-cover rounded border border-border cursor-pointer bg-black/20"
                   onClick={() => show(c)}
                   onError={(e) => {
                     const img = e.target as HTMLImageElement
                     if (c.image_id && !img.dataset.fallback) {
                       img.dataset.fallback = '1'
                       img.src = `/api/images/${c.image_id}/thumbnail`
                     }
                   }} />
              <button className="absolute top-1 right-1 btn-danger text-xs px-1 py-0.5 opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
                      onClick={() => remove(c)}>×</button>
              <div className="text-[10px] text-muted leading-tight truncate" title={JSON.stringify(c, null, 2)}>
                {c.content_id}
                {c.width && c.height ? ` · ${c.width}×${c.height}` : ''}
                {c.matte_id && c.matte_id !== 'none' ? ` · ${c.matte_id}` : ''}
              </div>
              <div className="flex gap-1 flex-wrap">
                <span className="badge text-[10px]">{CATEGORIES.find((x) => x.value === c.category_id)?.label ?? c.category_id}</span>
                {c.tv_image_id && <span className="badge text-[10px]">SAWSUBE</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Field({ label, children }: any) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>{children}
    </label>
  )
}
