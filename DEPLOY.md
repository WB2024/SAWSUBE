# SAWSUBE Deployment Guide

SAWSUBE is the backend that manages building and deploying Tizen apps to the Samsung Frame TV. It also serves the art/schedule management UI.

---

## Start SAWSUBE

```bash
cd /home/will/Github/SAWSUBE
nohup .venv/bin/python -m backend.main > /tmp/sawsube.log 2>&1 &
sleep 3 && curl -s http://127.0.0.1:8000/api/health
```

### Restart after Python code changes

```bash
kill $(pgrep -f "python.*backend.main") 2>/dev/null; sleep 2
cd /home/will/Github/SAWSUBE
nohup .venv/bin/python -m backend.main > /tmp/sawsube.log 2>&1 &
sleep 3 && curl -s http://127.0.0.1:8000/api/health
```

### Check if running

```bash
ps aux | grep "python.*backend.main" | grep -v grep
curl -s http://127.0.0.1:8000/api/health
```

---

## Deploy all TV apps

```bash
./deploy-all.sh
```

Or individually:

### Fieshzen (music player — Feishin on Tizen)
```bash
curl -X POST http://127.0.0.1:8000/api/tizenbrew/1/build-install-fieshzen
tail -f /tmp/sawsube.log
```

### Radarrzen (Radarr movie browser)
```bash
curl -X POST http://127.0.0.1:8000/api/tizenbrew/1/build-install-radarrzen
tail -f /tmp/sawsube.log
```

### Sonarrzen (Sonarr TV browser)
```bash
curl -X POST http://127.0.0.1:8000/api/tizenbrew/1/build-install-sonarrzen
tail -f /tmp/sawsube.log
```

---

## TV details

| | |
|---|---|
| TV | Samsung Frame 55 |
| IP | `192.168.1.202` |
| SDB port | `26101` |
| SAWSUBE TV ID | `1` |
| Tizen profile | `TestProfile` |

---

## Environment (.env)

Key variables in `.env`:

| Variable | Purpose |
|---|---|
| `FIESHZEN_FEISHIN_SRC_PATH` | Feishin React source (`/home/will/Github/feishin`) |
| `FIESHZEN_SRC_PATH` | Fieshzen Tizen wrapper (`/home/will/Github/Fieshzen`) |
| `FIESHZEN_TIZEN_PROFILE` | Signing profile |
| `Navidrome_URL` | Navidrome server |
| `Navidrome_username` / `Navidrome_password` | Auto-login credentials baked into Fieshzen |
| `RADARRZEN_SRC_PATH` | Radarrzen source (`/home/will/Github/radarrzen/src`) |
| `Radarr_URL` / `Radarr_API_KEY` | Injected into Radarrzen at build time |
| `SAWSUBE_URL` | External URL of SAWSUBE (`http://192.168.1.48:8000`) |

---

## Monitor logs

```bash
tail -f /tmp/sawsube.log
```

Success indicator: `Tizen application is successfully installed`

---

## API endpoints (quick ref)

```
GET  /api/health                                    Health check
GET  /api/tizenbrew/apps                            List curated apps
GET  /api/tizenbrew/1/installed-apps                Installed apps on TV 1
POST /api/tizenbrew/1/build-install-fieshzen        Build+deploy Fieshzen
POST /api/tizenbrew/1/build-install-radarrzen       Build+deploy Radarrzen
POST /api/tizenbrew/1/build-install-sonarrzen       Build+deploy Sonarrzen
POST /api/tizenbrew/1/sdb-connect                   Connect sdb to TV
```
