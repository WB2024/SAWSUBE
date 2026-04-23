import { useEffect, useState } from 'react'
import { api, TV, TVImage, TVStatus } from '../lib/api'
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
    setSettings({ ...settings, ...patch })
    try {
      await api.post(`/api/tvs/${tv.id}/art/settings`, patch)
      t.push({ type: 'success', text: 'Applied' })
    } catch (e: any) { t.push({ type: 'error', text: e.message }) }
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
        <div className="grid grid-cols-2 gap-3 text-sm">
          <Field label="Brightness (1–10)">
            <input type="number" min={1} max={10} className="input"
                   defaultValue={settings.brightness ?? 5}
                   onBlur={(e) => apply({ brightness: Number(e.target.value) })} />
          </Field>
          <Field label="Color temp (-5..5)">
            <input type="number" min={-5} max={5} className="input"
                   defaultValue={settings.color_temp ?? 0}
                   onBlur={(e) => apply({ color_temp: Number(e.target.value) })} />
          </Field>
          <Field label="Slideshow interval (mins)">
            <select className="input" defaultValue={settings.slideshow_interval ?? 3}
                    onChange={(e) => apply({ slideshow_interval: Number(e.target.value) })}>
              {[3, 5, 10, 15, 30, 60, 180, 360, 720, 1440].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </Field>
          <Field label="Shuffle">
            <input type="checkbox" defaultChecked={!!settings.shuffle}
                   onChange={(e) => apply({ shuffle: e.target.checked })} />
          </Field>
          <Field label="Motion timer">
            <select className="input" defaultValue={settings.motion_timer ?? 'off'}
                    onChange={(e) => apply({ motion_timer: e.target.value })}>
              {['off', '5', '15', '30', '60', '180'].map((v) => <option key={v}>{v}</option>)}
            </select>
          </Field>
          <Field label="Motion sensitivity (1-3)">
            <input type="number" min={1} max={3} className="input"
                   defaultValue={settings.motion_sensitivity ?? 2}
                   onBlur={(e) => apply({ motion_sensitivity: Number(e.target.value) })} />
          </Field>
          <Field label="Brightness sensor">
            <input type="checkbox" defaultChecked={!!settings.brightness_sensor}
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
            <div key={ti.id} className="relative group shrink-0">
              <img src={`/api/images/tv/${tv.id}/thumbnail/${ti.remote_id}`} alt=""
                   className="w-32 h-20 object-cover rounded border border-border cursor-pointer"
                   onClick={() => api.post(`/api/tvs/${tv.id}/art/current`, { tv_image_id: ti.id })}
                   onError={(e) => ((e.target as HTMLImageElement).src = `/api/images/${ti.image_id}/thumbnail`)} />
              <button className="absolute top-1 right-1 btn-danger text-xs px-1 py-0.5 opacity-0 group-hover:opacity-100"
                      onClick={() => api.del(`/api/images/${ti.image_id}/tv/${tv.id}`).then(refresh)}>×</button>
              <div className="absolute bottom-0 left-0 right-0 text-[10px] bg-black/60 text-white px-1 truncate">
                {ti.matte}
              </div>
            </div>
          ))}
          {tvImages.length === 0 && <div className="text-muted text-sm">None on TV yet.</div>}
        </div>
      </div>
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
