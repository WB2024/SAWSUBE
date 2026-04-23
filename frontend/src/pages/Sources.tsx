import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useToast } from '../components/Toast'

const TABS = ['Unsplash', 'NASA APOD', 'Rijksmuseum', 'Reddit'] as const
type Tab = typeof TABS[number]

export default function Sources() {
  const [tab, setTab] = useState<Tab>('Unsplash')
  useEffect(() => { document.title = 'SAWSUBE — Sources' }, [])
  return (
    <div className="space-y-4">
      <h1 className="text-2xl">Sources</h1>
      <div className="flex gap-2">
        {TABS.map((t) => (
          <button key={t} className={tab === t ? 'btn-primary' : 'btn-ghost'} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {tab === 'Unsplash' && <Unsplash />}
      {tab === 'NASA APOD' && <Nasa />}
      {tab === 'Rijksmuseum' && <Rijks />}
      {tab === 'Reddit' && <Reddit />}
    </div>
  )
}

function Grid({ items, onImport }: { items: any[]; onImport: (it: any) => void }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
      {items.map((it) => (
        <div key={it.id || it.url} className="card overflow-hidden">
          <img src={it.thumb || it.url} className="w-full aspect-[4/3] object-cover" />
          <div className="p-2 text-xs">
            <div className="truncate font-semibold">{it.title || '—'}</div>
            <div className="text-muted truncate">{it.credit || ''}</div>
            <button className="btn-primary mt-2 w-full" onClick={() => onImport(it)}>Import</button>
          </div>
        </div>
      ))}
    </div>
  )
}

function Unsplash() {
  const [q, setQ] = useState('landscape')
  const [items, setItems] = useState<any[]>([])
  const t = useToast()
  const search = async () => {
    try { setItems(await api.get(`/api/sources/unsplash/search?q=${encodeURIComponent(q)}`)) }
    catch (e: any) { t.push({ type: 'error', text: e.message }) }
  }
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <input className="input" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && search()} />
        <button className="btn-primary" onClick={search}>Search</button>
      </div>
      <Grid items={items} onImport={async (it) => {
        try { await api.post('/api/sources/unsplash/import', { id: it.id }); t.push({ type: 'success', text: 'Imported' }) }
        catch (e: any) { t.push({ type: 'error', text: e.message }) }
      }} />
    </div>
  )
}

function Nasa() {
  const [info, setInfo] = useState<any>(null)
  const t = useToast()
  useEffect(() => { api.get('/api/sources/nasa/apod').then(setInfo).catch(() => {}) }, [])
  if (!info) return <div className="text-muted">Loading…</div>
  if (info.unsupported) return <div className="card p-4 text-muted">Today's APOD is not an image ({info.media_type}).</div>
  return (
    <div className="card p-4 space-y-3">
      <div className="font-semibold">{info.title}</div>
      <img src={info.url} className="max-h-96 mx-auto" />
      <p className="text-sm text-muted">{info.explanation}</p>
      <button className="btn-primary" onClick={async () => {
        try { await api.post('/api/sources/nasa/apod/import'); t.push({ type: 'success', text: 'Imported' }) }
        catch (e: any) { t.push({ type: 'error', text: e.message }) }
      }}>Import to library</button>
    </div>
  )
}

function Rijks() {
  const [q, setQ] = useState('vermeer')
  const [items, setItems] = useState<any[]>([])
  const t = useToast()
  const search = async () => {
    try { setItems(await api.get(`/api/sources/rijksmuseum/search?q=${encodeURIComponent(q)}`)) }
    catch (e: any) { t.push({ type: 'error', text: e.message }) }
  }
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <input className="input" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && search()} />
        <button className="btn-primary" onClick={search}>Search</button>
      </div>
      <Grid items={items} onImport={async (it) => {
        try { await api.post('/api/sources/rijksmuseum/import', { id: it.id }); t.push({ type: 'success', text: 'Imported' }) }
        catch (e: any) { t.push({ type: 'error', text: e.message }) }
      }} />
    </div>
  )
}

function Reddit() {
  const [sub, setSub] = useState('EarthPorn')
  const [sort, setSort] = useState('top')
  const [tt, setTt] = useState('week')
  const [items, setItems] = useState<any[]>([])
  const t = useToast()
  const fetchIt = async () => {
    try { setItems(await api.get(`/api/sources/reddit/fetch?sub=${sub}&sort=${sort}&t=${tt}&limit=24`)) }
    catch (e: any) { t.push({ type: 'error', text: e.message }) }
  }
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <input className="input" value={sub} onChange={(e) => setSub(e.target.value)} placeholder="subreddit" />
        <select className="input w-28" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option>top</option><option>hot</option><option>new</option>
        </select>
        <select className="input w-28" value={tt} onChange={(e) => setTt(e.target.value)}>
          <option>day</option><option>week</option><option>month</option><option>year</option><option>all</option>
        </select>
        <button className="btn-primary" onClick={fetchIt}>Fetch</button>
      </div>
      <Grid items={items} onImport={async (it) => {
        try {
          await api.post('/api/sources/reddit/import', {
            url: it.url, id: it.id,
            meta: { title: it.title, credit: it.credit, html: it.html, subreddit: it.subreddit },
          })
          t.push({ type: 'success', text: 'Imported' })
        } catch (e: any) { t.push({ type: 'error', text: e.message }) }
      }} />
    </div>
  )
}
