type Listener = (msg: any) => void

class WSClient {
  private ws: WebSocket | null = null
  private listeners = new Set<Listener>()
  private retry = 1000

  connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const host = location.host
    this.ws = new WebSocket(`${proto}://${host}/ws`)
    this.ws.onmessage = (e) => {
      try { this.listeners.forEach((l) => l(JSON.parse(e.data))) } catch {}
    }
    this.ws.onclose = () => { setTimeout(() => this.connect(), this.retry); this.retry = Math.min(this.retry * 2, 15000) }
    this.ws.onopen = () => { this.retry = 1000 }
  }
  on(l: Listener) { this.listeners.add(l); return () => this.listeners.delete(l) }
}

export const wsClient = new WSClient()
