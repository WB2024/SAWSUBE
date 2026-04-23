import { useEffect, useState } from 'react'
import { api, Folder, TV } from '../lib/api'
import { useToast } from '../components/Toast'

export default function Settings() {
  const [folders, setFolders] = useState<Folder[]>([])
  const [newPath, setNewPath] = useState('')
  const [tvs, setTvs] = useState<TV[]>([])
  const t = useToast()

  const load = async () => {
    setFolders(await api.get<Folder[]>('/api/sources/folders'))
    setTvs(await api.get<TV[]>('/api/tvs'))
  }
  useEffect(() => { document.title = 'SAWSUBE — Settings'; load() }, [])

  const addFolder = async () => {
    if (!newPath) return
    try { await api.post('/api/sources/folders', { path: newPath, is_active: true, auto_display: false }); setNewPath(''); load() }
    catch (e: any) { t.push({ type: 'error', text: e.message }) }
  }

  return (
    <div className="space-y-4 max-w-2xl">
      <h1 className="text-2xl">Settings</h1>

      <Section title="Watch folders">
        <div className="flex gap-2">
          <input className="input" placeholder="/path/to/folder" value={newPath} onChange={(e) => setNewPath(e.target.value)} />
          <button className="btn-primary" onClick={addFolder}>Add</button>
        </div>
        <div className="space-y-1 mt-3">
          {folders.map((f) => (
            <div key={f.id} className="flex justify-between items-center text-sm border border-border rounded px-3 py-2">
              <span className="truncate">{f.path}</span>
              <div className="flex gap-2">
                <button className="btn-ghost" onClick={() => api.post(`/api/sources/folders/${f.id}/scan`).then((r: any) => t.push({ type: 'success', text: `Scanned: ${r.added} new` }))}>Scan now</button>
                <button className="btn-danger" onClick={() => api.del(`/api/sources/folders/${f.id}`).then(load)}>Remove</button>
              </div>
            </div>
          ))}
          {folders.length === 0 && <div className="text-muted text-sm">None.</div>}
        </div>
      </Section>

      <Section title="TVs">
        {tvs.map((t) => (
          <div key={t.id} className="flex justify-between text-sm py-1">
            <span>{t.name} · {t.ip} · {t.mac || 'no MAC'}</span>
            <button className="btn-danger" onClick={() => confirm('Remove TV?') && api.del(`/api/tvs/${t.id}`).then(load)}>Remove</button>
          </div>
        ))}
      </Section>

      <Section title="Environment notes">
        <p className="text-sm text-muted">
          API keys (Unsplash, Rijksmuseum, NASA) and other defaults are configured via the
          <code className="mx-1 px-1 bg-card rounded">.env</code> file in the backend directory.
          Edit and restart the backend to apply.
        </p>
        <ul className="text-xs text-muted list-disc pl-5 space-y-0.5">
          <li>UNSPLASH_API_KEY</li>
          <li>RIJKSMUSEUM_API_KEY</li>
          <li>TV_RESOLUTION (4K | 1080p)</li>
          <li>PORTRAIT_HANDLING (blur | crop | skip)</li>
          <li>IMAGE_FOLDER (downloaded source images)</li>
        </ul>
      </Section>

      <Section title="Danger zone">
        <button className="btn-danger" onClick={async () => {
          if (!confirm('Wipe all art from every TV? Local DB is kept.')) return
          for (const tv of tvs) {
            const items: any[] = await api.get(`/api/images/tv/${tv.id}`)
            for (const it of items) await api.del(`/api/images/${it.image_id}/tv/${tv.id}`)
          }
          t.push({ type: 'success', text: 'Done' })
        }}>Wipe all art from TVs</button>
      </Section>
    </div>
  )
}

function Section({ title, children }: any) {
  return (
    <div className="card p-4 space-y-2">
      <div className="font-semibold">{title}</div>
      {children}
    </div>
  )
}
