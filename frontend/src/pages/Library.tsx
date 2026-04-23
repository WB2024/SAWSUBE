import { useEffect, useRef, useState, DragEvent } from 'react'
import { api, Image, TV } from '../lib/api'
import { useToast } from '../components/Toast'

export default function Library() {
  const [images, setImages] = useState<Image[]>([])
  const [tvs, setTvs] = useState<TV[]>([])
  const [filter, setFilter] = useState({ source: '', tag: '', favourite: false, q: '' })
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [uploading, setUploading] = useState<{ name: string; pct: number }[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  const toast = useToast()

  const load = async () => {
    const params = new URLSearchParams()
    if (filter.source) params.set('source', filter.source)
    if (filter.tag) params.set('tag', filter.tag)
    if (filter.favourite) params.set('favourite', 'true')
    if (filter.q) params.set('q', filter.q)
    setImages(await api.get<Image[]>('/api/images?' + params.toString()))
  }
  useEffect(() => { document.title = 'SAWSUBE — Library'; load(); api.get<TV[]>('/api/tvs').then(setTvs) }, [])
  useEffect(() => { load() }, [filter])

  const upload = async (files: FileList | File[]) => {
    const arr = Array.from(files)
    setUploading(arr.map((f) => ({ name: f.name, pct: 0 })))
    try {
      await api.upload<Image[]>('/api/images/upload', arr)
      toast.push({ type: 'success', text: `Uploaded ${arr.length} file(s)` })
      load()
    } catch (e: any) {
      toast.push({ type: 'error', text: e.message })
    } finally {
      setUploading([])
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    if (e.dataTransfer.files.length) upload(e.dataTransfer.files)
  }

  const toggleSel = (id: number) => {
    setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  const sendTo = async (id: number, tv_id: number) => {
    try {
      await api.post(`/api/images/${id}/send/${tv_id}`)
      toast.push({ type: 'success', text: 'Sent to TV' })
    } catch (e: any) { toast.push({ type: 'error', text: e.message }) }
  }
  const fav = async (id: number) => { await api.post(`/api/images/${id}/favourite`); load() }
  const del = async (id: number) => {
    if (!confirm('Delete image?')) return
    await api.del(`/api/images/${id}?also_from_tv=true`); load()
  }

  const bulkSend = async (tv_id: number) => {
    for (const id of selected) await sendTo(id, tv_id)
    setSelected(new Set())
  }
  const bulkDelete = async () => {
    if (!confirm(`Delete ${selected.size} images?`)) return
    for (const id of selected) await api.del(`/api/images/${id}?also_from_tv=true`)
    setSelected(new Set()); load()
  }

  return (
    <div className="space-y-4" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
      <div className="flex justify-between items-center flex-wrap gap-2">
        <h1 className="text-2xl">Library</h1>
        <div className="flex gap-2">
          <input className="input w-48" placeholder="Search filename" value={filter.q} onChange={(e) => setFilter({ ...filter, q: e.target.value })} />
          <select className="input w-32" value={filter.source} onChange={(e) => setFilter({ ...filter, source: e.target.value })}>
            <option value="">All sources</option>
            <option>local</option><option>unsplash</option><option>nasa</option><option>rijksmuseum</option><option>reddit</option>
          </select>
          <input className="input w-28" placeholder="Tag" value={filter.tag} onChange={(e) => setFilter({ ...filter, tag: e.target.value })} />
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={filter.favourite} onChange={(e) => setFilter({ ...filter, favourite: e.target.checked })} /> Fav</label>
          <button className="btn-primary" onClick={() => fileRef.current?.click()}>Upload</button>
          <input ref={fileRef} type="file" multiple className="hidden" accept="image/*" onChange={(e) => e.target.files && upload(e.target.files)} />
        </div>
      </div>

      {selected.size > 0 && (
        <div className="card p-3 flex items-center gap-2">
          <span className="text-sm">{selected.size} selected</span>
          <select className="input w-40" onChange={(e) => e.target.value && bulkSend(Number(e.target.value))} value="">
            <option value="">Send all to TV…</option>
            {tvs.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <button className="btn-danger" onClick={bulkDelete}>Delete selected</button>
          <button className="btn-ghost" onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
        {images.map((img) => (
          <div key={img.id} className={`card overflow-hidden relative group ${selected.has(img.id) ? 'ring-2 ring-accent' : ''}`}>
            <img src={`/api/images/${img.id}/thumbnail`} alt={img.filename} className="w-full aspect-[4/3] object-cover cursor-pointer"
                 onClick={() => toggleSel(img.id)} />
            <div className="p-2 text-xs">
              <div className="truncate" title={img.filename}>{img.filename}</div>
              <div className="flex justify-between items-center text-muted mt-1">
                <span className="badge">{img.source}</span>
                <button onClick={() => fav(img.id)} title="Favourite">{img.is_favourite ? '★' : '☆'}</button>
              </div>
            </div>
            <div className="absolute inset-x-0 bottom-0 p-2 bg-black/70 opacity-0 group-hover:opacity-100 transition flex flex-col gap-1">
              <select className="input text-xs" onChange={(e) => e.target.value && sendTo(img.id, Number(e.target.value))} value="">
                <option value="">Send to TV…</option>
                {tvs.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
              <div className="flex gap-1">
                <button className="btn-danger text-xs flex-1" onClick={() => del(img.id)}>Del</button>
                <button className="btn-ghost text-xs flex-1" onClick={() => {
                  const t = prompt('Tags (comma)', img.tags || '')
                  if (t !== null) api.put(`/api/images/${img.id}/tags`, { tags: t }).then(load)
                }}>Tag</button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {uploading.length > 0 && (
        <div className="fixed bottom-4 left-4 card p-3 space-y-2 w-72 z-40">
          <div className="text-sm font-semibold">Uploading…</div>
          {uploading.map((u, i) => <div key={i} className="text-xs truncate">{u.name}</div>)}
        </div>
      )}
    </div>
  )
}
