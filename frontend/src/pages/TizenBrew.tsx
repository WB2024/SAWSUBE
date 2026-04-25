import { useEffect, useMemo, useState } from 'react'
import { api, TV } from '../lib/api'
import { useToast } from '../components/Toast'
import { useWS } from '../lib/hooks'

// ── SAWSUBE palette ─────────────────────────────────────────────────────────
const C = {
  bg: '#0F1923',
  card: '#1E2A35',
  fg: '#F4F1ED',
  muted: '#A09890',
  accent: '#C8612A',
  ok: '#4A7C5F',
  warn: '#C49A3C',
  err: '#A33228',
  border: '#1E2A35',
}

// ── Types ───────────────────────────────────────────────────────────────────
type Tools = { sdb_path: string | null; tizen_path: string | null; found: boolean }
type TizenInfo = {
  tv_id: number; ip: string; developer_mode: boolean; developer_ip: string | null
  tizen_version: string | null; tizen_year: number | null; model_name: string | null
  requires_certificate: boolean; error: string | null
}
type SdbStatus = {
  tv_id: number; sdb_available: boolean; tizen_available: boolean
  tv_connected: boolean; error: string | null
}
type State = {
  id: number; tv_id: number; tizen_version: string | null; tizen_year: number | null
  developer_mode_detected: boolean; sdb_connected: boolean
  tizenbrew_installed: boolean; tizenbrew_version: string | null
  certificate_profile: string | null; last_checked: string | null; notes: string | null
}
type AppDef = {
  id: string; name: string; description: string; icon_url: string | null
  source_type: string; source: string; category: string
}
type InstalledApp = {
  id: number; tv_id: number; app_name: string; app_source: string
  installed_at: string; wgt_path: string | null; version: string | null
}
type ProgressMsg = { tv_id: number; step: string; message: string; progress: number }

// ── Page ────────────────────────────────────────────────────────────────────
export default function TizenBrew() {
  const [tab, setTab] = useState<'setup' | 'apps' | 'builder'>('setup')
  const [tvs, setTvs] = useState<TV[]>([])
  const [tvId, setTvId] = useState<number | null>(null)
  const [progress, setProgress] = useState<ProgressMsg | null>(null)
  const [log, setLog] = useState<ProgressMsg[]>([])

  useEffect(() => {
    document.title = 'SAWSUBE — TizenBrew'
    api.get<TV[]>('/api/tvs').then((list) => {
      setTvs(list)
      if (list[0]) setTvId(list[0].id)
    })
  }, [])

  useWS((m) => {
    if (m?.type !== 'tizenbrew_install_progress') return
    setProgress(m)
    setLog((l) => [...l.slice(-200), m])
  })

  const clearLog = () => { setLog([]); setProgress(null) }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl" style={{ color: C.fg, fontFamily: 'var(--font-display)', letterSpacing: '0.04em' }}>
            TizenBrew
          </h1>
          <div style={{ color: C.muted }} className="text-sm">
            Homebrew apps for your Samsung Frame — install, manage, build.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span style={{ color: C.muted }} className="text-xs">TV:</span>
          <select
            className="input"
            style={{ minWidth: '180px' }}
            value={tvId ?? ''}
            onChange={(e) => setTvId(e.target.value ? Number(e.target.value) : null)}
          >
            {tvs.length === 0 && <option value="">No TVs</option>}
            {tvs.map((t) => <option key={t.id} value={t.id}>{t.name} · {t.ip}</option>)}
          </select>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b" style={{ borderColor: C.card }}>
        {([
          ['setup', 'Setup'],
          ['apps', 'Apps'],
          ['builder', 'Module Builder'],
        ] as const).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            style={{
              background: 'transparent',
              border: 'none',
              padding: '10px 18px',
              cursor: 'pointer',
              color: tab === k ? C.accent : C.muted,
              borderBottom: tab === k ? `2px solid ${C.accent}` : '2px solid transparent',
              fontFamily: 'var(--font-display)',
              letterSpacing: '0.05em',
              fontSize: '14px',
            }}
          >{label}</button>
        ))}
      </div>

      {/* No TV warning */}
      {!tvId && (
        <div className="card p-6" style={{ background: C.card, borderColor: C.card, color: C.muted }}>
          Add a TV first via <span style={{ color: C.accent }}>Discover</span>.
        </div>
      )}

      {tvId && tab === 'setup' && (
        <SetupTab tvId={tvId} progress={progress} log={log} onClearLog={clearLog} />
      )}
      {tvId && tab === 'apps' && (
        <AppsTab tvId={tvId} progress={progress} log={log} onClearLog={clearLog} />
      )}
      {tab === 'builder' && <ModuleBuilderTab />}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Reusable bits
// ─────────────────────────────────────────────────────────────────────────────

function StatusDot({ kind }: { kind: 'ok' | 'warn' | 'err' | 'pending' }) {
  const c = kind === 'ok' ? C.ok : kind === 'warn' ? C.warn : kind === 'err' ? C.err : C.muted
  const ch = kind === 'ok' ? '✓' : kind === 'warn' ? '!' : kind === 'err' ? '✕' : '·'
  return (
    <span style={{
      width: '24px', height: '24px', borderRadius: '50%',
      background: c, color: '#0F1923', display: 'inline-flex',
      alignItems: 'center', justifyContent: 'center',
      fontSize: '14px', fontWeight: 700, flexShrink: 0,
    }}>{ch}</span>
  )
}

function StepCard({
  num, title, status, children,
}: {
  num: number; title: string; status: 'ok' | 'warn' | 'err' | 'pending'; children: React.ReactNode
}) {
  return (
    <div className="card p-5" style={{ background: C.card, borderColor: '#2A3845' }}>
      <div className="flex items-center gap-3 mb-4">
        <StatusDot kind={status} />
        <div style={{ color: C.muted, fontSize: '12px', letterSpacing: '0.1em' }}>STEP {num}</div>
        <div style={{ color: C.fg, fontFamily: 'var(--font-display)', fontSize: '18px' }}>{title}</div>
      </div>
      {children}
    </div>
  )
}

function ProgressBar({ value }: { value: number }) {
  return (
    <div style={{
      width: '100%', height: '8px', background: '#0F1923',
      borderRadius: '4px', overflow: 'hidden',
    }}>
      <div style={{
        width: `${Math.max(0, Math.min(100, value))}%`,
        height: '100%', background: C.accent,
        transition: 'width 200ms ease',
      }} />
    </div>
  )
}

function LogBox({ entries, onClear }: { entries: ProgressMsg[]; onClear: () => void }) {
  if (entries.length === 0) return null
  return (
    <div className="mt-3">
      <div className="flex justify-between items-center mb-1">
        <div style={{ color: C.muted, fontSize: '11px', letterSpacing: '0.1em' }}>LOG</div>
        <button className="btn-ghost text-xs" onClick={onClear} style={{ padding: '2px 8px' }}>Clear</button>
      </div>
      <div style={{
        background: '#080E15', color: '#9CB1C6', fontFamily: 'ui-monospace, Menlo, monospace',
        fontSize: '12px', padding: '10px 12px', borderRadius: '6px',
        maxHeight: '200px', overflowY: 'auto', border: '1px solid #2A3845',
      }}>
        {entries.map((e, i) => (
          <div key={i} style={{ color: e.step === 'error' ? C.err : e.step === 'done' ? C.ok : '#9CB1C6' }}>
            [{e.step}] {e.message}
          </div>
        ))}
      </div>
    </div>
  )
}

function InfoBanner({ kind, children }: { kind: 'info' | 'warn' | 'err' | 'ok'; children: React.ReactNode }) {
  const colors = {
    info: { bg: 'rgba(196,154,60,0.10)', border: C.warn, fg: C.fg },
    warn: { bg: 'rgba(196,154,60,0.15)', border: C.warn, fg: C.fg },
    err:  { bg: 'rgba(163,50,40,0.15)', border: C.err, fg: C.fg },
    ok:   { bg: 'rgba(74,124,95,0.15)', border: C.ok, fg: C.fg },
  }[kind]
  return (
    <div style={{
      background: colors.bg, borderLeft: `4px solid ${colors.border}`,
      color: colors.fg, padding: '12px 16px', borderRadius: '4px', fontSize: '13px',
    }}>{children}</div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Setup wizard
// ─────────────────────────────────────────────────────────────────────────────

function SetupTab({
  tvId, progress, log, onClearLog,
}: {
  tvId: number; progress: ProgressMsg | null; log: ProgressMsg[]; onClearLog: () => void
}) {
  const t = useToast()
  const [tools, setTools] = useState<Tools | null>(null)
  const [info, setInfo] = useState<TizenInfo | null>(null)
  const [sdb, setSdb] = useState<SdbStatus | null>(null)
  const [state, setState] = useState<State | null>(null)
  const [profiles, setProfiles] = useState<string[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [confetti, setConfetti] = useState(false)
  const [serverIps, setServerIps] = useState<string[]>([])

  // Cert form
  const [certName, setCertName] = useState('SAWSUBE')
  const [certPwd, setCertPwd] = useState('')
  const [certCountry, setCertCountry] = useState('GB')

  const loadTools = async () => {
    try { setTools(await api.get<Tools>('/api/tizenbrew/tools')) } catch (e: any) { t.push({ type: 'error', text: e.message }) }
  }
  const loadInfo = async () => {
    try { setInfo(await api.get<TizenInfo>(`/api/tizenbrew/${tvId}/info`)) } catch (e: any) { setInfo({ tv_id: tvId, ip: '', developer_mode: false, developer_ip: null, tizen_version: null, tizen_year: null, model_name: null, requires_certificate: false, error: e.message }) }
  }
  const loadState = async () => {
    try { setState(await api.get<State>(`/api/tizenbrew/${tvId}/status`)) } catch {}
  }
  const loadProfiles = async () => {
    try {
      const r = await api.get<{ profiles: string[] }>('/api/tizenbrew/certificates')
      setProfiles(r.profiles || [])
    } catch { setProfiles([]) }
  }

  useEffect(() => {
    loadTools(); loadInfo(); loadState(); loadProfiles()
    api.get<{ ips: string[] }>('/api/server-ips').then(r => setServerIps(r.ips || [])).catch(() => {})
  }, [tvId])

  // React to install completion
  useEffect(() => {
    if (!progress) return
    if (progress.step === 'done') {
      loadState(); loadProfiles()
      setBusy(null)
      setConfetti(true)
      t.push({ type: 'success', text: progress.message })
      setTimeout(() => setConfetti(false), 4000)
    } else if (progress.step === 'error') {
      setBusy(null)
      t.push({ type: 'error', text: progress.message })
    }
  }, [progress?.message, progress?.step])

  const sdbConnect = async () => {
    setBusy('sdb')
    try {
      const r = await api.post<SdbStatus>(`/api/tizenbrew/${tvId}/sdb-connect`)
      setSdb(r)
      t.push({ type: r.tv_connected ? 'success' : 'error', text: r.tv_connected ? 'TV connected via sdb' : (r.error || 'sdb connect failed') })
    } catch (e: any) { t.push({ type: 'error', text: e.message }) }
    finally { setBusy(null) }
  }

  const createCert = async () => {
    if (!certPwd) { t.push({ type: 'error', text: 'Password required' }); return }
    setBusy('cert')
    onClearLog()
    try {
      await api.post(`/api/tizenbrew/${tvId}/certificate`, {
        profile_name: certName, password: certPwd, country: certCountry,
      })
      t.push({ type: 'info', text: 'Certificate creation started — watch the log below…' })
    } catch (e: any) {
      setBusy(null)
      t.push({ type: 'error', text: e.message })
    }
  }

  const installTB = async () => {
    setBusy('install'); onClearLog()
    try {
      await api.post(`/api/tizenbrew/${tvId}/install-tizenbrew`)
      t.push({ type: 'info', text: 'TizenBrew installation started…' })
    } catch (e: any) { setBusy(null); t.push({ type: 'error', text: e.message }) }
  }

  // Step statuses
  const s1: 'ok' | 'err' = tools?.found ? 'ok' : 'err'
  const s2: 'ok' | 'warn' | 'pending' = info?.developer_mode ? 'ok' : info?.error ? 'warn' : 'pending'
  const s3: 'ok' | 'warn' | 'pending' = (sdb?.tv_connected ?? state?.sdb_connected) ? 'ok' : 'pending'
  const s4: 'ok' | 'warn' | 'pending' = !info?.requires_certificate
    ? 'ok'
    : (state?.certificate_profile || profiles.length > 0) ? 'ok' : 'warn'
  const s5: 'ok' | 'pending' = state?.tizenbrew_installed ? 'ok' : 'pending'

  return (
    <div className="space-y-4">
      {confetti && <Confetti />}

      {/* Step 1 — Tools */}
      <StepCard num={1} title="Tizen Studio CLI" status={s1}>
        {tools?.found ? (
          <div style={{ color: C.fg }} className="text-sm">
            Found: <code style={{ color: C.accent }}>{tools.sdb_path}</code> · <code style={{ color: C.accent }}>{tools.tizen_path}</code>
          </div>
        ) : (
          <div className="space-y-3">
            <InfoBanner kind="err">
              Tizen Studio CLI tools (<code>sdb</code>, <code>tizen</code>) not found on this server.
              They are required to install apps on the TV.
            </InfoBanner>

            <InfoBanner kind="warn">
              <b>Note:</b> If the download page returns a 403 error, disable your VPN — Samsung's CDN (CloudFront) blocks most VPN IP ranges.
            </InfoBanner>

            <div style={{ color: C.fg, fontSize: '13px', lineHeight: 1.8 }}>
              <div style={{ color: C.muted, fontSize: '11px', letterSpacing: '0.1em', marginBottom: '6px' }}>INSTALLATION OPTIONS</div>

              <div style={{ marginBottom: '10px' }}>
                <b>Option A — CLI-only package</b> (recommended, ~200 MB, Linux 64-bit)
                <br />
                No IDE needed — just the <code>sdb</code> + <code>tizen</code> binaries:
                <br />
                <code style={{
                  display: 'block', background: '#080E15', padding: '8px 10px',
                  borderRadius: '4px', margin: '6px 0', fontSize: '12px',
                  color: '#9CB1C6', fontFamily: 'ui-monospace, Menlo, monospace',
                  userSelect: 'all',
                }}>
                  wget https://download.tizen.org/sdk/Installer/tizen-studio_6.0/web-cli_Tizen_Studio_6.0_ubuntu-64.bin && chmod +x web-cli_Tizen_Studio_6.0_ubuntu-64.bin && ./web-cli_Tizen_Studio_6.0_ubuntu-64.bin
                </code>
                After install, the tools will be at <code>~/tizen-studio/tools/</code> — SAWSUBE finds them automatically.
              </div>

              <div style={{ marginBottom: '10px' }}>
                <b>Option B — Full Tizen Studio IDE</b> (3 GB, required if Option A fails):
                <br />
                <a href="https://developer.samsung.com/smarttv/develop/getting-started/setting-up-sdk/installing-tv-sdk.html"
                   target="_blank" rel="noreferrer"
                   style={{ color: C.accent, textDecoration: 'underline' }}>
                  developer.samsung.com — Installing TV SDK
                </a>
                {' '}<span style={{ color: C.muted }}>→ download the .bin GUI installer, run it, install the <b>TV Extensions</b> package</span>
              </div>

              <div>
                <b>Option C — Manual path override</b>: if tools are in a non-standard location, set
                {' '}<code>TIZEN_SDB_PATH</code> and <code>TIZEN_CLI_PATH</code> in your <code>.env</code> file and restart SAWSUBE.
              </div>
            </div>

            <button className="btn-primary" onClick={loadTools}>Refresh</button>
          </div>
        )}
      </StepCard>

      {/* Step 2 — Developer Mode */}
      <StepCard num={2} title="Developer Mode on TV" status={s2}>
        {info?.developer_mode ? (
          <div className="space-y-2">
            <div className="flex flex-wrap gap-2 items-center">
              <span className="badge" style={{ borderColor: C.ok, color: C.ok }}>Developer Mode ON</span>
              {info.tizen_version && <span className="badge">Tizen {info.tizen_version}</span>}
              {info.tizen_year && <span className="badge">{info.tizen_year}</span>}
              {info.model_name && <span className="badge">{info.model_name}</span>}
              {info.requires_certificate && <span className="badge" style={{ borderColor: C.warn, color: C.warn }}>Cert required</span>}
            </div>
            {info.developer_ip && (
              <div style={{ color: C.muted }} className="text-xs">
                Host PC IP set on TV: <code>{info.developer_ip}</code>
              </div>
            )}
            <button className="btn-ghost" onClick={loadInfo}>Re-check</button>
          </div>
        ) : (
          <div className="space-y-3">
            <InfoBanner kind="warn">
              Developer Mode not detected on the TV at <code>{info?.ip}</code>. Enable it manually:
            </InfoBanner>
            <ol style={{ color: C.fg, fontSize: '13px', lineHeight: 1.7, paddingLeft: '20px', listStyle: 'decimal' }}>
              <li>On your Samsung TV remote, press <b>Home</b></li>
              <li>Open the <b>Apps</b> panel</li>
              <li>On the numeric remote (or screen keypad), enter <b>1 2 3 4 5</b></li>
              <li>The Developer Mode dialog appears — toggle <b>Developer Mode → On</b></li>
              <li>Enter your SAWSUBE server's IP in the <b>Host PC IP</b> field</li>
              <li>Press <b>OK</b> and <b>reboot the TV</b></li>
              <li>Click <b>Check Again</b> below</li>
            </ol>
            {info?.error && <InfoBanner kind="err">{info.error}</InfoBanner>}
            <button className="btn-primary" onClick={loadInfo}>Check Again</button>
          </div>
        )}
      </StepCard>

      {/* Step 3 — sdb connect */}
      <StepCard num={3} title="Connect via sdb" status={s3}>
        <div className="space-y-3">
          {/* IP mismatch warning */}
          {info?.developer_mode && info.developer_ip && (() => {
            // Detect if the TV's registered developer IP doesn't look like this machine's IP.
            // We can't know the server's external IP from the browser, so warn generically
            // when the developer_ip is set to something that looks like a different host.
            const devIp = info.developer_ip
            return (
              <InfoBanner kind="warn">
                TV has Host PC IP set to <code>{devIp}</code>.
                Make sure this matches the IP of the machine running SAWSUBE.
                {' '}If wrong, go back to the TV: <b>Apps → 12345 → change Host PC IP → reboot TV</b>.
                <br />
                Your server's local IP:{' '}
                {serverIps.length > 0
                  ? serverIps.map(ip => (
                      <code key={ip} style={{ color: C.accent, marginRight: '8px' }}><b>{ip}</b></code>
                    ))
                  : <code style={{ color: C.accent }}>run <b>hostname -I</b> in a terminal</code>
                }
              </InfoBanner>
            )
          })()}

          <div style={{ color: C.muted }} className="text-sm">
            {(sdb?.tv_connected ?? state?.sdb_connected)
              ? '✓ TV is connected on the Samsung Debug Bridge'
              : 'Bring the TV onto sdb so we can push apps to it. TV must be on and on the same network.'}
          </div>
          {sdb?.error && !sdb.tv_connected && (
            <InfoBanner kind="err">
              {sdb.error.includes('timed out')
                ? <>sdb connect timed out. Most likely cause: the <b>Host PC IP</b> on the TV ({info?.developer_ip || '?'}) doesn't match this server's IP, so the TV rejects the connection. Update it on the TV and retry.
                  <br />Also verify the TV is powered on and on the same network.
                  </>
                : sdb.error}
            </InfoBanner>
          )}
          <button className="btn-primary" onClick={sdbConnect}
                  disabled={!info?.developer_mode || !tools?.found || busy === 'sdb'}>
            {busy === 'sdb' ? 'Connecting…' : 'Connect TV'}
          </button>
        </div>
      </StepCard>

      {/* Step 4 — Cert (conditional) */}
      {info?.requires_certificate && (
        <StepCard num={4} title="Samsung Developer Certificate" status={s4}>
          {(state?.certificate_profile || profiles.length > 0) ? (
            <div style={{ color: C.fg }} className="text-sm">
              ✓ Certificate ready —{' '}
              <code style={{ color: C.accent }}>
                {state?.certificate_profile || profiles[0]}
              </code>
            </div>
          ) : (
            <div className="space-y-3">
              <InfoBanner kind="warn">
                Your TV runs Tizen {info.tizen_version || '7+'} ({info.tizen_year}+).
                Samsung requires a developer certificate to install apps.
              </InfoBanner>

              <InfoBanner kind="info">
                <b>How it works:</b> SAWSUBE will run <code>tizen certificate</code> to create a developer
                certificate. If the <b>Samsung Certificate Extension</b> is installed in Tizen Studio's
                Package Manager, it tries Samsung-signed mode first (browser opens for Samsung account).
                Otherwise it creates a standard developer certificate automatically — <b>no browser required</b>.
                <br /><br />
                To install Samsung Certificate Extension: open <b>Tizen Studio → Package Manager → Extension SDK → Samsung Certificate Extension</b>.
              </InfoBanner>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <label className="flex flex-col gap-1">
                  <span style={{ color: C.muted }} className="text-xs">Profile name</span>
                  <input className="input" value={certName} onChange={(e) => setCertName(e.target.value)} />
                </label>
                <label className="flex flex-col gap-1">
                  <span style={{ color: C.muted }} className="text-xs">Password</span>
                  <input className="input" type="password" value={certPwd} onChange={(e) => setCertPwd(e.target.value)} />
                </label>
                <label className="flex flex-col gap-1">
                  <span style={{ color: C.muted }} className="text-xs">Country (2 letter)</span>
                  <input className="input" maxLength={2} value={certCountry}
                         onChange={(e) => setCertCountry(e.target.value.toUpperCase())} />
                </label>
              </div>
              <button className="btn-primary" onClick={createCert} disabled={busy === 'cert'}>
                {busy === 'cert' ? 'Working…' : 'Create Certificate'}
              </button>
              <div style={{ color: C.muted }} className="text-xs">
                If Samsung Certificate Extension is installed, a browser window will open for Samsung sign-in.
                Otherwise a standard developer certificate is created immediately.
              </div>
            </div>
          )}
          {(busy === 'cert' || log.some((l) => l.step === 'certificate')) && (
            <LogBox entries={log.filter((l) => ['certificate', 'done', 'error'].includes(l.step))}
                    onClear={onClearLog} />
          )}
        </StepCard>
      )}

      {/* Step 5 — Install TizenBrew */}
      <StepCard num={info?.requires_certificate ? 5 : 4} title="Install TizenBrew" status={s5}>
        {state?.tizenbrew_installed ? (
          <div className="space-y-3">
            <div style={{ color: C.fg }} className="text-sm">
              ✓ TizenBrew installed{state.tizenbrew_version ? ` (${state.tizenbrew_version})` : ''}.
              Launch it from your TV's app list.
            </div>
            <button className="btn-ghost" onClick={installTB} disabled={busy === 'install'}>
              {busy === 'install' ? 'Re-installing…' : 'Re-install'}
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            <button className="btn-primary" onClick={installTB}
                    disabled={busy === 'install' || !tools?.found || !info?.developer_mode}>
              {busy === 'install' ? 'Installing…' : 'Install TizenBrew'}
            </button>
            {state?.notes && !busy && <InfoBanner kind="err">{state.notes}</InfoBanner>}
          </div>
        )}
        {(busy === 'install' || log.length > 0) && (
          <div className="mt-3 space-y-2">
            {progress && busy === 'install' && (
              <>
                <div style={{ color: C.fg }} className="text-sm flex justify-between">
                  <span>{progress.message}</span>
                  <span style={{ color: C.muted }}>{progress.progress}%</span>
                </div>
                <ProgressBar value={progress.progress} />
              </>
            )}
            <LogBox entries={log} onClear={onClearLog} />
          </div>
        )}
      </StepCard>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Apps
// ─────────────────────────────────────────────────────────────────────────────

function AppsTab({
  tvId, progress, log, onClearLog,
}: { tvId: number; progress: ProgressMsg | null; log: ProgressMsg[]; onClearLog: () => void }) {
  const t = useToast()
  const [apps, setApps] = useState<AppDef[]>([])
  const [installed, setInstalled] = useState<InstalledApp[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [showInstalled, setShowInstalled] = useState(false)

  // Custom install
  const [customType, setCustomType] = useState<'github' | 'wgt_url'>('github')
  const [customSrc, setCustomSrc] = useState('')

  const load = async () => {
    try { setApps(await api.get<AppDef[]>('/api/tizenbrew/apps')) } catch {}
    try { setInstalled(await api.get<InstalledApp[]>(`/api/tizenbrew/${tvId}/installed-apps`)) } catch {}
  }
  useEffect(() => { load() }, [tvId])

  useEffect(() => {
    if (!progress) return
    if (progress.step === 'done') {
      setBusy(null); load()
      t.push({ type: 'success', text: progress.message })
    } else if (progress.step === 'error') {
      setBusy(null)
      t.push({ type: 'error', text: progress.message })
    }
  }, [progress?.message, progress?.step])

  const installedSources = useMemo(
    () => new Set(installed.map((i) => i.app_source)),
    [installed],
  )

  const install = async (app: AppDef) => {
    setBusy(app.id); onClearLog()
    try {
      await api.post(`/api/tizenbrew/${tvId}/install-app`, app)
      t.push({ type: 'info', text: `Installing ${app.name}…` })
    } catch (e: any) { setBusy(null); t.push({ type: 'error', text: e.message }) }
  }

  const normalizeGithubSource = (src: string): string => {
    // Strip full GitHub URL and trim to just owner/repo (first two path segments)
    // e.g. https://github.com/foo/bar/releases/download/v1/app.wgt → foo/bar
    const stripped = src.trim()
      .replace(/^https?:\/\/github\.com\//, '')
      .replace(/\.git$/, '')
      .replace(/\/$/, '')
    const parts = stripped.split('/')
    return parts.length >= 2 ? `${parts[0]}/${parts[1]}` : stripped
  }

  const installCustom = async () => {
    if (!customSrc.trim()) { t.push({ type: 'error', text: 'Enter a source' }); return }
    const normalizedSrc = customType === 'github' ? normalizeGithubSource(customSrc) : customSrc.trim()
    const def: AppDef = {
      id: 'custom-' + Date.now(),
      name: normalizedSrc.split('/').pop() || 'Custom App',
      description: `Custom (${customType})`,
      icon_url: null,
      source_type: customType,
      source: normalizedSrc,
      category: 'Custom',
    }
    install(def)
    setCustomSrc('')
  }

  return (
    <div className="space-y-4">
      {/* Curated grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {apps.map((a) => {
          const isInstalled = installedSources.has(`${a.source_type}:${a.source}`)
          const isBusy = busy === a.id
          const isTizenBrewOnly = a.source_type === 'tizenbrew'
          return (
            <div key={a.id} className="card p-4 flex flex-col gap-3"
                 style={{ background: C.card, borderColor: '#2A3845' }}>
              <div className="flex gap-3 items-start">
                <div style={{
                  width: '48px', height: '48px', background: '#0F1923',
                  borderRadius: '8px', display: 'flex', alignItems: 'center',
                  justifyContent: 'center', overflow: 'hidden', flexShrink: 0,
                }}>
                  {a.icon_url
                    ? <img src={a.icon_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                           onError={(e) => ((e.currentTarget.style.display = 'none'))} />
                    : <span style={{ color: C.accent, fontSize: '20px' }}>▣</span>}
                </div>
                <div className="flex-1 min-w-0">
                  <div style={{ color: C.fg, fontFamily: 'var(--font-display)', fontSize: '15px' }}>{a.name}</div>
                  <div className="flex gap-1 mt-1 flex-wrap">
                    <span className="badge" style={{ borderColor: C.accent, color: C.accent }}>{a.category}</span>
                    {isTizenBrewOnly && (
                      <span className="badge" style={{ borderColor: C.warn, color: C.warn }}>Via TizenBrew</span>
                    )}
                  </div>
                </div>
              </div>
              <div style={{ color: C.muted, fontSize: '13px', flex: 1 }}>{a.description}</div>
              {!isTizenBrewOnly && (
                <div style={{ color: C.muted, fontSize: '11px' }}>
                  <code>{a.source_type}:{a.source}</code>
                </div>
              )}
              {isTizenBrewOnly ? (
                <div className="p-3 rounded text-sm" style={{ background: '#0F1923', color: C.warn, border: `1px solid ${C.warn}33` }}>
                  Open <b>TizenBrew</b> on your TV and find <b>{a.name}</b> in the store to install it.
                </div>
              ) : isInstalled ? (
                <div className="flex gap-2 items-center">
                  <span className="badge" style={{ borderColor: C.ok, color: C.ok }}>✓ Installed</span>
                  <button className="btn-ghost flex-1" onClick={() => install(a)} disabled={isBusy}>
                    {isBusy ? 'Re-installing…' : 'Re-install'}
                  </button>
                </div>
              ) : (
                <button className="btn-primary" onClick={() => install(a)} disabled={isBusy}>
                  {isBusy ? 'Installing…' : 'Install'}
                </button>
              )}
            </div>
          )
        })}
      </div>

      {/* Live progress for app install */}
      {busy && progress && (
        <div className="card p-4 space-y-2" style={{ background: C.card, borderColor: '#2A3845' }}>
          <div style={{ color: C.fg }} className="text-sm flex justify-between">
            <span>{progress.message}</span>
            <span style={{ color: C.muted }}>{progress.progress}%</span>
          </div>
          <ProgressBar value={progress.progress} />
          <LogBox entries={log} onClear={onClearLog} />
        </div>
      )}

      {/* Custom install */}
      <div className="card p-4 space-y-3" style={{ background: C.card, borderColor: '#2A3845' }}>
        <div style={{ color: C.fg, fontFamily: 'var(--font-display)', fontSize: '16px' }}>Install Custom App</div>
        <div style={{ color: C.muted }} className="text-sm">
          GitHub repo (e.g. <code>user/repo</code>) — fetches latest release WGT/TPK — or a direct <code>.wgt</code>/<code>.tpk</code> URL.
        </div>
        <div className="flex flex-col sm:flex-row gap-2">
          <select className="input" style={{ maxWidth: '180px' }}
                  value={customType} onChange={(e) => setCustomType(e.target.value as any)}>
            <option value="github">GitHub repo</option>
            <option value="wgt_url">Direct URL</option>
          </select>
          <input className="input flex-1"
                 placeholder={customType === 'github' ? 'user/repo' : 'https://example.com/app.wgt'}
                 value={customSrc} onChange={(e) => setCustomSrc(e.target.value)} />
          <button className="btn-primary" onClick={installCustom} disabled={busy !== null}>Install</button>
        </div>
      </div>

      {/* Installed list */}
      <div className="card" style={{ background: C.card, borderColor: '#2A3845' }}>
        <button onClick={() => setShowInstalled((v) => !v)}
                style={{
                  width: '100%', textAlign: 'left', padding: '14px 16px',
                  background: 'transparent', border: 'none', color: C.fg,
                  cursor: 'pointer', fontFamily: 'var(--font-display)', fontSize: '15px',
                  display: 'flex', justifyContent: 'space-between',
                }}>
          <span>Installed apps ({installed.length})</span>
          <span style={{ color: C.muted }}>{showInstalled ? '▾' : '▸'}</span>
        </button>
        {showInstalled && (
          <div style={{ borderTop: '1px solid #2A3845' }} className="p-4 space-y-2">
            {installed.length === 0 && (
              <div style={{ color: C.muted }} className="text-sm">No apps installed yet.</div>
            )}
            {installed.map((i) => (
              <div key={i.id} className="flex justify-between text-sm" style={{ color: C.fg }}>
                <span>
                  {i.app_name}
                  {i.version && <span style={{ color: C.muted }}> · {i.version}</span>}
                </span>
                <span style={{ color: C.muted }} className="text-xs">
                  {new Date(i.installed_at).toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Module Builder
// ─────────────────────────────────────────────────────────────────────────────

const COMMON_KEYS = [
  'MediaPlayPause', 'MediaPlay', 'MediaPause', 'MediaStop',
  'MediaFastForward', 'MediaRewind', 'MediaTrackNext', 'MediaTrackPrevious',
  'ColorF0Red', 'ColorF1Green', 'ColorF2Yellow', 'ColorF3Blue',
  '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
]

function ModuleBuilderTab() {
  const t = useToast()
  const [pkgType, setPkgType] = useState<'app' | 'mods'>('app')
  const [pkgName, setPkgName] = useState('my-tizenbrew-app')
  const [appName, setAppName] = useState('My App')
  const [websiteUrl, setWebsiteUrl] = useState('')
  const [appPath, setAppPath] = useState('app/index.html')
  const [keys, setKeys] = useState<string[]>([])
  const [includeService, setIncludeService] = useState(false)
  const [evalOnStart, setEvalOnStart] = useState(false)
  const [description, setDescription] = useState('')

  const [out, setOut] = useState<{
    package_json: any; readme: string; instructions: string
    service_file: string | null; inject_file: string | null
  } | null>(null)
  const [outTab, setOutTab] = useState<'pkg' | 'readme' | 'service' | 'inject'>('pkg')

  const toggleKey = (k: string) => setKeys((cur) => cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k])

  const generate = async () => {
    if (!pkgName.trim()) { t.push({ type: 'error', text: 'Package name required' }); return }
    if (!appName.trim()) { t.push({ type: 'error', text: 'App name required' }); return }
    if (pkgType === 'mods' && !websiteUrl.trim()) { t.push({ type: 'error', text: 'Website URL required for mods' }); return }
    try {
      const res = await api.post<typeof out & object>('/api/tizenbrew/module/scaffold', {
        package_name: pkgName,
        app_name: appName,
        package_type: pkgType,
        website_url: websiteUrl || null,
        app_path: appPath || null,
        keys,
        service_file: includeService ? 'service.js' : null,
        evaluate_on_start: evalOnStart,
        description: description || null,
      })
      setOut(res as any)
      t.push({ type: 'success', text: 'Scaffold generated' })
    } catch (e: any) { t.push({ type: 'error', text: e.message }) }
  }

  const copy = (text: string) => {
    navigator.clipboard.writeText(text).then(
      () => t.push({ type: 'success', text: 'Copied' }),
      () => t.push({ type: 'error', text: 'Copy failed' }),
    )
  }

  const downloadZip = async () => {
    if (!out) return
    try {
      const JSZip = (await import('jszip')).default
      const zip = new JSZip()
      zip.file('package.json', JSON.stringify(out.package_json, null, 2))
      zip.file('README.md', out.readme)
      if (out.service_file) zip.file('service.js', out.service_file)
      if (out.inject_file) zip.file('inject.js', out.inject_file)
      if (pkgType === 'app') {
        zip.folder('app')?.file(
          'index.html',
          `<!doctype html>\n<html>\n  <head><meta charset="utf-8"><title>${appName}</title></head>\n  <body><h1>${appName}</h1></body>\n</html>\n`,
        )
      }
      const blob = await zip.generateAsync({ type: 'blob' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${pkgName}.zip`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e: any) { t.push({ type: 'error', text: 'ZIP failed: ' + e.message }) }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Form */}
      <div className="card p-5 space-y-4" style={{ background: C.card, borderColor: '#2A3845' }}>
        <div style={{ color: C.fg, fontFamily: 'var(--font-display)', fontSize: '16px' }}>Module spec</div>

        <Field label="Module type">
          <div className="flex gap-2">
            <button className={pkgType === 'app' ? 'btn-primary' : 'btn-ghost'} onClick={() => setPkgType('app')}>App Module</button>
            <button className={pkgType === 'mods' ? 'btn-primary' : 'btn-ghost'} onClick={() => setPkgType('mods')}>Site Modification</button>
          </div>
        </Field>

        <Field label="Package name (npm, kebab-case)">
          <input className="input" value={pkgName}
                 onChange={(e) => setPkgName(e.target.value.toLowerCase().replace(/[^a-z0-9\-]/g, '-'))} />
        </Field>

        <Field label="App name (display)">
          <input className="input" value={appName} onChange={(e) => setAppName(e.target.value)} />
        </Field>

        {pkgType === 'mods' && (
          <Field label="Website URL to modify">
            <input className="input" placeholder="https://example.com" value={websiteUrl}
                   onChange={(e) => setWebsiteUrl(e.target.value)} />
          </Field>
        )}

        {pkgType === 'app' && (
          <Field label="App entry path">
            <input className="input" value={appPath} onChange={(e) => setAppPath(e.target.value)} />
          </Field>
        )}

        <Field label="TV remote keys to register">
          <div className="flex flex-wrap gap-1 max-h-44 overflow-y-auto p-2"
               style={{ background: '#0F1923', borderRadius: '6px', border: '1px solid #2A3845' }}>
            {COMMON_KEYS.map((k) => (
              <button key={k} onClick={() => toggleKey(k)}
                      style={{
                        padding: '4px 10px', borderRadius: '4px',
                        border: '1px solid ' + (keys.includes(k) ? C.accent : '#2A3845'),
                        background: keys.includes(k) ? C.accent : 'transparent',
                        color: keys.includes(k) ? C.fg : C.muted,
                        fontSize: '11px', cursor: 'pointer',
                      }}>{k}</button>
            ))}
          </div>
        </Field>

        <div className="flex gap-4 flex-wrap">
          <label className="flex items-center gap-2" style={{ color: C.fg, fontSize: '13px' }}>
            <input type="checkbox" checked={includeService} onChange={(e) => setIncludeService(e.target.checked)} />
            Include service worker (Node.js)
          </label>
          {pkgType === 'mods' && (
            <label className="flex items-center gap-2" style={{ color: C.fg, fontSize: '13px' }}>
              <input type="checkbox" checked={evalOnStart} onChange={(e) => setEvalOnStart(e.target.checked)} />
              Evaluate on document start
            </label>
          )}
        </div>

        <Field label="Description">
          <textarea className="input" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>

        <button className="btn-primary w-full" onClick={generate}>Generate Module Scaffold</button>
      </div>

      {/* Output */}
      <div className="card p-5 space-y-3" style={{ background: C.card, borderColor: '#2A3845' }}>
        <div className="flex justify-between items-center">
          <div style={{ color: C.fg, fontFamily: 'var(--font-display)', fontSize: '16px' }}>Output</div>
          {out && (
            <div className="flex gap-2">
              <button className="btn-ghost" onClick={downloadZip}>Download ZIP</button>
            </div>
          )}
        </div>

        {!out && (
          <div style={{ color: C.muted }} className="text-sm">
            Fill the form and click <b>Generate</b>. You'll get a complete folder you can publish to npm.
          </div>
        )}

        {out && (
          <div className="space-y-3">
            <div className="flex gap-1 border-b" style={{ borderColor: '#2A3845' }}>
              {([
                ['pkg', 'package.json'],
                ['readme', 'README.md'],
                ...(out.service_file ? [['service', 'service.js'] as const] : []),
                ...(out.inject_file ? [['inject', 'inject.js'] as const] : []),
              ] as const).map(([k, label]) => (
                <button key={k} onClick={() => setOutTab(k as any)}
                        style={{
                          background: 'transparent', border: 'none',
                          padding: '6px 12px', cursor: 'pointer',
                          color: outTab === k ? C.accent : C.muted,
                          borderBottom: outTab === k ? `2px solid ${C.accent}` : '2px solid transparent',
                          fontSize: '12px', fontFamily: 'ui-monospace, Menlo, monospace',
                        }}>{label}</button>
              ))}
            </div>

            {outTab === 'pkg' && (
              <CodeBlock content={JSON.stringify(out.package_json, null, 2)} onCopy={copy} />
            )}
            {outTab === 'readme' && (
              <CodeBlock content={out.readme} onCopy={copy} />
            )}
            {outTab === 'service' && out.service_file && (
              <CodeBlock content={out.service_file} onCopy={copy} />
            )}
            {outTab === 'inject' && out.inject_file && (
              <CodeBlock content={out.inject_file} onCopy={copy} />
            )}

            <div className="card p-3" style={{ background: '#0F1923', borderColor: '#2A3845' }}>
              <div style={{ color: C.accent, fontSize: '12px', letterSpacing: '0.1em', marginBottom: '6px' }}>
                NEXT STEPS
              </div>
              <pre style={{
                color: C.fg, fontSize: '12px', whiteSpace: 'pre-wrap',
                fontFamily: 'ui-monospace, Menlo, monospace',
              }}>{out.instructions}</pre>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function CodeBlock({ content, onCopy }: { content: string; onCopy: (s: string) => void }) {
  return (
    <div style={{ position: 'relative' }}>
      <button onClick={() => onCopy(content)}
              style={{
                position: 'absolute', top: '8px', right: '8px',
                background: '#2A3845', color: C.fg, border: 'none',
                padding: '4px 10px', borderRadius: '4px', cursor: 'pointer',
                fontSize: '11px',
              }}>Copy</button>
      <pre style={{
        background: '#080E15', color: '#9CB1C6',
        padding: '14px', borderRadius: '6px',
        fontSize: '12px', fontFamily: 'ui-monospace, Menlo, monospace',
        maxHeight: '420px', overflow: 'auto',
        border: '1px solid #2A3845', whiteSpace: 'pre-wrap',
      }}>{content}</pre>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span style={{ color: C.muted }} className="text-xs">{label}</span>
      {children}
    </label>
  )
}

// ── Confetti (CSS only) ─────────────────────────────────────────────────────

function Confetti() {
  const pieces = Array.from({ length: 60 })
  const colors = [C.accent, C.ok, C.warn, '#E8845A', '#9CB1C6']
  return (
    <div style={{
      position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 60, overflow: 'hidden',
    }}>
      <style>{`
        @keyframes sawsube-confetti-fall {
          0% { transform: translateY(-10vh) rotate(0deg); opacity: 1; }
          100% { transform: translateY(110vh) rotate(720deg); opacity: 0; }
        }
      `}</style>
      {pieces.map((_, i) => {
        const left = Math.random() * 100
        const delay = Math.random() * 0.6
        const dur = 2.5 + Math.random() * 1.5
        const color = colors[i % colors.length]
        const size = 6 + Math.random() * 6
        return (
          <div key={i} style={{
            position: 'absolute', top: 0, left: `${left}%`,
            width: `${size}px`, height: `${size * 0.4}px`,
            background: color, borderRadius: '2px',
            animation: `sawsube-confetti-fall ${dur}s linear ${delay}s forwards`,
          }} />
        )
      })}
    </div>
  )
}
