const BASE = ''

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
    ...init,
  })
  if (!r.ok) {
    const t = await r.text()
    throw new Error(`${r.status}: ${t}`)
  }
  const ct = r.headers.get('content-type') || ''
  if (ct.includes('json')) return r.json()
  return (await r.text()) as any
}

export const api = {
  get: <T,>(p: string) => req<T>(p),
  post: <T,>(p: string, body?: any) =>
    req<T>(p, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  put: <T,>(p: string, body?: any) =>
    req<T>(p, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),
  del: <T,>(p: string) => req<T>(p, { method: 'DELETE' }),
  upload: async <T,>(p: string, files: File[]): Promise<T> => {
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    const r = await fetch(BASE + p, { method: 'POST', body: fd })
    if (!r.ok) throw new Error(await r.text())
    return r.json()
  },
}

export type TV = {
  id: number; name: string; ip: string; mac?: string | null
  port: number; model?: string | null; year?: string | null
  added_at: string; last_seen?: string | null
}
export type TVStatus = {
  id: number; online: boolean; artmode: boolean | null
  current: string | null; paired: boolean; error?: string | null
}
export type Image = {
  id: number; filename: string; file_hash: string; file_size: number
  width: number; height: number; source: string; source_meta: any
  uploaded_at: string; is_favourite: boolean; tags: string | null
}
export type TVImage = {
  id: number; tv_id: number; image_id: number; remote_id: string | null
  uploaded_at: string; is_on_tv: boolean; matte: string
}
export type Schedule = {
  id: number; tv_id: number; name: string; mode: string
  source_filter: any; interval_mins: number
  time_from: string | null; time_to: string | null
  days_of_week: string; is_active: boolean
}
export type Folder = { id: number; path: string; is_active: boolean; auto_display: boolean }
