# SAWSUBE

> Your Frame. Your Art. Your Apps. Your Rules.

A self-hosted control centre for Samsung Frame TVs — manage art, schedule rotations, browse free image sources, install and manage third-party apps, scan and remove Samsung bloatware, and control every Art Mode setting, all from your browser.

No Samsung account. No subscription. No cloud.

**Built by WB**

---

## Features

### Art Management
- **Multi-TV support** — manage multiple Frame TVs simultaneously, each with independent controls and schedules
- **Full Art Mode control** — brightness, colour temperature, slideshow interval, shuffle, motion timer, motion sensitivity, brightness sensor, matte/border style
- **Image library** — upload images via drag-and-drop or file picker, with SHA256 deduplication, tagging, favourites, and multi-select bulk actions
- **Intelligent image processing** — every image is automatically processed before upload:
  - EXIF orientation correction
  - ICC colour profile conversion to sRGB (critical — prevents washed-out colours on the Frame)
  - Portrait & square images get Instagram-style blur-fill (blurred, desaturated background, sharp image centred on top)
  - Landscape crop to 16:9 centred, then Lanczos resize to 3840×2160 (4K) or 1920×1080 (1080p)
  - Subtle unsharp mask to compensate for display softening
  - All EXIF metadata stripped from output
  - Results cached by hash — re-uploads skip reprocessing
- **Scheduling** — automated art rotation with random, sequential, or favourites-weighted modes; optional time-of-day windows and day-of-week filters
- **Folder watcher** — point it at a folder and new images appear in the library automatically
- **External sources** — browse and import from Unsplash, Pexels, Pixabay, Openverse, NASA Astronomy Picture of the Day, Rijksmuseum, and Reddit image posts

### App Management (TizenBrew)
- **One-click app installation** onto your Samsung TV from a curated catalogue:
  - **Radarrzen** — Radarr movie manager, built from local source with your credentials pre-injected
  - **Sonarrzen** — Sonarr TV-show manager, same credential injection
  - **Fieshzen** — Navidrome/Subsonic music player (built from Feishin source)
  - **Castafiorezen** — lightweight native Tizen music player for Navidrome
  - **Jellyfin** — downloaded from jeppevinkel/jellyfin-tizen-builds GitHub releases
  - **Moonlight** — PC game streaming via NVIDIA GameStream / Sunshine
  - **TizenTube** — ad-free YouTube (installed via TizenBrew on the TV itself)
- **Certificate management** — create and manage Tizen author/distributor certificates for signing WGT packages
- **WGT builder** — scaffold, build, sign, and push custom Tizen web apps directly from the UI
- **Real-time install progress** — WebSocket progress bar for every install step
- **Credential injection** — Radarr, Sonarr, Navidrome, and SAWSUBE URLs/API keys are baked into the WGT at build time so apps open pre-configured on the TV
- **TMDB discovery** — movie/show discovery powered by The Movie Database, injected at build time

### TV Debloat
- **App scanner** — lists every package installed on the TV via sdb, cross-referenced against a curated database of known Samsung apps
- **Safety classification** — each app rated `safe` / `optional` / `caution` / `system` with descriptions and Frame TV–specific warnings
- **Bulk removal** — remove multiple apps in one click with real-time progress; hard-coded protection for essential Art Mode packages
- **Removal log** — full history of everything removed, with timestamps

### General
- **TV discovery** — UPnP/SSDP scan finds Frame TVs on your LAN automatically
- **Wake-on-LAN** — power on a TV by MAC address
- **Real-time updates** — WebSocket pushes live TV status, upload progress, install progress, and schedule fires to the UI without polling
- **Dark mode** — persists in browser storage
- **Image proxy** — SAWSUBE proxies Radarr and Navidrome cover art to the browser (and to Tizen apps) with long-lived cache headers and optional resizing, so apps never need to expose your Radarr/Navidrome credentials to external networks

---

## Requirements

| Requirement | Notes |
|---|---|
| Python 3.11+ | Backend runtime |
| Node.js 20+ | Only needed to build the frontend UI |
| Samsung Frame TV (2021+) | Tested on LS03A/B/C/D. Tizen 7.0 (2022 model) verified. Older models best-effort |
| Same LAN | All TV communication is local |
| **Tizen Studio** (optional) | Required only for TizenBrew app installation and Debloat |

---

## Quick Start

### Option 1 — Docker (recommended for art management only)

```bash
cp .env.example .env   # edit as needed
docker compose up --build
```

Open **http://localhost:8000**.

> **Linux:** For SSDP TV discovery and Wake-on-LAN to work, uncomment `network_mode: host` in `docker-compose.yml`.

> **Note:** TizenBrew app installation and Debloat require `tizen` and `sdb` CLIs from Tizen Studio, which must be installed natively. These features do not work inside Docker unless you mount the Tizen Studio binaries.

---

### Option 2 — Native on Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

### Option 3 — Native on Windows

```cmd
start.bat
```

Both scripts:
1. Create a Python virtual environment in `.venv` if one doesn't exist
2. Install all Python dependencies
3. Copy `.env.example` to `.env` if absent
4. Build the React frontend with npm (if Node is installed)
5. Start the app at **http://localhost:8000**

---

## Full Setup Guide

### Step 1 — Configure your environment

Copy the example config and edit:

```bash
cp .env.example .env
```

#### Core settings

| Variable | Default | Description |
|---|---|---|
| `TV_DEFAULT_IP` | *(empty)* | Pre-fills the IP field when adding a TV manually |
| `IMAGE_FOLDER` | `./data/images` | Where downloaded source images are stored |
| `DB_PATH` | `./data/sawsube.db` | SQLite database path |
| `TOKEN_DIR` | `./data/tokens` | Pairing token files — **must persist across restarts** |
| `IMAGE_CACHE_DIR` | `./data/cache` | Processed 4K JPEG cache |
| `THUMBNAIL_DIR` | `./data/thumbnails` | 400px preview cache |
| `TV_RESOLUTION` | `4K` | `4K` (3840×2160) or `1080p` (1920×1080) |
| `PORTRAIT_HANDLING` | `blur` | `blur` (recommended), `crop`, or `skip` |
| `HOST` | `0.0.0.0` | Interface to bind |
| `PORT` | `8000` | Port the backend listens on |
| `POLL_INTERVAL_SECS` | `20` | How often the backend polls each TV |
| `SAWSUBE_URL` | `http://localhost:8000` | Public URL of this SAWSUBE instance — used by Tizen apps to phone home |

#### Image source API keys

| Variable | Where to get it |
|---|---|
| `UNSPLASH_API_KEY` | [unsplash.com/developers](https://unsplash.com/developers) — free |
| `PEXELS_API_KEY` | [pexels.com/api](https://www.pexels.com/api/) — free |
| `PIXABAY_API_KEY` | [pixabay.com/api/docs](https://pixabay.com/api/docs/) — free |
| `OPENVERSE_CLIENT_ID` / `OPENVERSE_CLIENT_SECRET` | [api.openverse.org](https://api.openverse.org/) — free |
| `RIJKSMUSEUM_API_KEY` | [data.rijksmuseum.nl](https://data.rijksmuseum.nl/object-metadata/api/) — free |
| `NASA_API_KEY` | [api.nasa.gov](https://api.nasa.gov) — free (optional; public key works with rate limits) |

Reddit requires no API key.

#### Radarrzen (movie manager on TV)

| Variable | Description |
|---|---|
| `RADARR_URL` | Your Radarr instance URL, e.g. `http://192.168.1.10:7878` |
| `RADARR_API_KEY` | Found in Radarr → Settings → General |
| `RADARRZEN_SRC_PATH` | Absolute path to `radarrzen/src` on this machine |
| `RADARRZEN_TIZEN_PROFILE` | Tizen signing profile name (default: `SAWSUBE`) |
| `TMDB_API_KEY` | [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) — free; powers movie discovery |

#### Sonarrzen (TV-show manager on TV)

| Variable | Description |
|---|---|
| `SONARR_URL` | Your Sonarr instance URL, e.g. `http://192.168.1.10:8989` |
| `SONARR_API_KEY` | Found in Sonarr → Settings → General |
| `SONARRZEN_SRC_PATH` | Absolute path to `Sonarrzen/src` on this machine |
| `SONARRZEN_TIZEN_PROFILE` | Tizen signing profile name (default: `SAWSUBE`) |

#### Fieshzen / Castafiorezen (music players on TV)

| Variable | Description |
|---|---|
| `NAVIDROME_URL` | Your Navidrome URL, e.g. `http://192.168.1.10:4533` |
| `NAVIDROME_USERNAME` | Navidrome login username |
| `NAVIDROME_PASSWORD` | Navidrome login password |
| `NAVIDROME_SERVER_NAME` | Display name shown in the app |
| `FIESHZEN_FEISHIN_SRC_PATH` | Path to the local `feishin` repo root |
| `FIESHZEN_SRC_PATH` | Path to the `Fieshzen/tizen` directory |
| `FIESHZEN_TIZEN_PROFILE` | Tizen signing profile name |
| `CASTAFIOREZEN_SRC_PATH` | Path to the `Castafiorezen` source directory |
| `CASTAFIOREZEN_TIZEN_PROFILE` | Tizen signing profile name |

#### Tizen CLI paths

These are auto-discovered from `~/tizen-studio` but can be overridden explicitly (useful if you have multiple Tizen Studio installations):

| Variable | Description |
|---|---|
| `TIZEN_CLI_PATH` | Full path to the `tizen` binary, e.g. `~/tizen-studio/tools/ide/bin/tizen` |
| `TIZEN_SDB_PATH` | Full path to `sdb`, e.g. `~/tizen-studio2/tools/sdb` |

> **Important:** If you have `tizen-extension-platform` or another Tizen Studio variant on your `PATH`, set these explicitly. SAWSUBE always prefers `~/tizen-studio` over PATH but the explicit overrides take priority over everything.

---

### Step 2 — Add and pair your TV

1. Open **http://localhost:8000** → **Discover** tab
2. Click **Scan Network** to auto-find Frame TVs via UPnP/SSDP, or enter the IP manually
3. Click **Add** then go to **TV Control**
4. Click **Pair** — a prompt appears on your TV. Press **Allow** with your remote within 90 seconds
5. The token is saved to `data/tokens/` and reused automatically

> Give your TV a **static IP address** in your router's DHCP settings. A changing IP breaks the connection.

---

### Step 3 — Set up Tizen Studio (for app installs and debloat)

TizenBrew app installation and TV debloat both require the Tizen Studio CLI tools (`tizen` and `sdb`). The SAWSUBE UI walks you through this in the **TizenBrew** tab under **Setup**.

#### Install Tizen Studio

Download from [developer.samsung.com/tizen/run.html](https://developer.samsung.com/tizen/run.html) and install to `~/tizen-studio`.

On Linux you will also need the JDK:
```bash
sudo apt install default-jdk
```

#### Enable Developer Mode on your TV

1. On your TV: Settings → Support → About This TV → note your TV's IP
2. Navigate to Settings → Support → About This TV → click the model number 5 times → "Developer mode" dialog appears
3. Enter your PC's IP address and enable Developer Mode
4. Reboot the TV
5. Connect: `~/tizen-studio2/tools/sdb connect YOUR_TV_IP`

#### Create a Tizen certificate profile

This is required to sign WGT packages for installation on Tizen 7+ TVs (2022+):

1. In Tizen Studio IDE: Tools → Certificate Manager → + → Samsung → Device (for TV)
2. Enter your DUID (found in TV developer mode settings or via `sdb shell cat /opt/etc/data_info.xml | grep DUID`)
3. Name the profile (e.g. `TestProfile` or `SAWSUBE`) — use this name in `RADARRZEN_TIZEN_PROFILE` etc.

Alternatively, use the TizenBrew → Setup → Certificates section in SAWSUBE to create a profile through the CLI.

---

### Step 4 — Install TV apps via TizenBrew

Go to **TizenBrew** in SAWSUBE:

1. **Setup tab**: verify Tizen tools are found (green ticks), check developer mode and sdb connection
2. **Apps tab**: select your TV from the dropdown, click **Install** on any curated app

For `local_build` apps (Radarrzen, Sonarrzen, Fieshzen, Castafiorezen), SAWSUBE:
- Copies the source directory to a temp folder
- Injects your credentials (URL, API key, SAWSUBE URL) directly into `sawsube-config.js`
- Packages and signs the WGT with your Tizen profile in one step
- Pushes it to the TV via sdb

No re-signing. No manual credential entry on the TV.

---

### Step 5 — Debloat your TV (optional)

Go to **Debloat** → select your TV → **Scan**. SAWSUBE lists every installed package with safety ratings. Select apps to remove and click **Remove Selected**. Essential Art Mode packages are protected and cannot be removed.

---

## UI Pages

### Dashboard
Live overview — online/offline status, Art Mode state, currently displayed image, recent history, quick actions.

### Library
Full image collection. Drag-and-drop upload, filter by source/tag/favourites, hover for quick actions (send to TV, delete, edit tags), multi-select bulk operations.

### TV Control
Per-TV panel: pair, power, Art Mode on/off, brightness, colour temperature, slideshow settings, matte selector, currently displayed images.

### Discover
Scan the network for Frame TVs or add by IP.

### Sources
Import images from Unsplash, Pexels, Pixabay, Openverse, NASA APOD, Rijksmuseum, Reddit.

### Schedules
Automated art rotation — random, sequential, or favourites-weighted. Optional time windows and day-of-week filters.

### TizenBrew
Install and manage third-party apps on your Samsung TV. Three tabs:
- **Setup** — Tizen Studio tool status, developer mode check, certificate management
- **Apps** — curated app catalogue with one-click install and real-time progress
- **Builder** — scaffold, build, and sign custom Tizen web app modules

### Debloat
Scan and selectively remove Samsung bloatware. Safety-rated app database, real-time removal progress, full removal log.

### Settings
Watch folders, TV management, environment variable reference, danger zone.

---

## Repository Structure

```
SAWSUBE/
├── backend/
│   ├── main.py                     # FastAPI app entry point + lifespan
│   ├── config.py                   # Settings via pydantic-settings + .env
│   ├── database.py                 # Async SQLAlchemy engine + session
│   ├── schemas.py                  # Core Pydantic models
│   ├── schemas_tizenbrew.py        # TizenBrew request/response models
│   ├── schemas_debloat.py          # Debloat request/response models
│   ├── models/
│   │   ├── tv.py
│   │   ├── image.py
│   │   ├── schedule.py
│   │   ├── history.py
│   │   ├── folder.py
│   │   ├── tizenbrew.py            # TizenBrewState + TizenBrewInstalledApp
│   │   └── debloat.py              # RemovalLog
│   ├── routers/
│   │   ├── tv.py                   # /api/tvs
│   │   ├── art.py                  # /api/tvs/{id}/art
│   │   ├── images.py               # /api/images
│   │   ├── schedule.py             # /api/schedules
│   │   ├── sources.py              # /api/sources
│   │   ├── meta.py                 # /api/history + /api/stats
│   │   ├── tizenbrew.py            # /api/tizenbrew
│   │   ├── debloat.py              # /api/debloat
│   │   ├── radarr.py               # /api/radarr (image proxy + TMDB)
│   │   ├── sonarr.py               # /api/sonarr (image proxy)
│   │   ├── navidrome.py            # /api/navidrome (cover art proxy)
│   │   └── ws.py                   # /ws WebSocket
│   ├── services/
│   │   ├── tv_manager.py           # Persistent connection pool + polling
│   │   ├── image_processor.py      # Full Pillow image pipeline
│   │   ├── scheduler.py            # APScheduler wrapper
│   │   ├── watcher.py              # watchdog folder monitor
│   │   ├── discovery.py            # UPnP/SSDP scan
│   │   ├── ws_manager.py           # WebSocket broadcast hub
│   │   ├── tizenbrew_service.py    # App build, sign, install, debloat tools
│   │   ├── debloat_service.py      # App scan, safety classification, removal
│   │   └── sources/
│   │       ├── common.py
│   │       ├── unsplash.py
│   │       ├── pexels.py
│   │       ├── pixabay.py
│   │       ├── openverse.py
│   │       ├── nasa_apod.py
│   │       ├── rijksmuseum.py
│   │       └── reddit.py
│   └── data/
│       └── tizen_apps.json         # Curated debloat app database
├── frontend/
│   └── src/
│       └── pages/
│           ├── Dashboard.tsx
│           ├── Library.tsx
│           ├── TVControl.tsx
│           ├── Discover.tsx
│           ├── Sources.tsx
│           ├── Schedules.tsx
│           ├── TizenBrew.tsx
│           ├── Debloat.tsx
│           └── Settings.tsx
├── data/                           # Created at runtime — gitignored
├── docker-compose.yml
├── Dockerfile.backend
├── start.sh
├── start.bat
└── .env.example
```

---

## Companion Apps

These are separate repos that SAWSUBE builds and installs onto your TV:

| App | Repo | Description |
|---|---|---|
| **Radarrzen** | `radarrzen/` | Radarr movie manager — browse library, search TMDB, monitor downloads |
| **Sonarrzen** | `Sonarrzen/` | Sonarr TV-show manager — browse shows, manage seasons/episodes |
| **Fieshzen** | `Fieshzen/` | Navidrome music player built from Feishin web source |
| **Castafiorezen** | `Castafiorezen/` | Lightweight native Tizen music player for Navidrome |

SAWSUBE clones/builds these from local source paths you configure in `.env`. Credentials are injected at build time — the TV apps never need you to type a URL or API key manually.

---

## TV Communication

All TV communication goes through [NickWaterton's fork of samsung-tv-ws-api](https://github.com/NickWaterton/samsung-tv-ws-api):

```
samsungtvws[async,encrypted] @ git+https://github.com/NickWaterton/samsung-tv-ws-api.git
```

The backend maintains a **persistent connection pool** — one WebSocket per TV, opened lazily and kept alive. Connections are never opened per-request (doing so triggers the pairing prompt on every action). Every TV call is wrapped in try/except — an offline TV never crashes the app.

---

## Troubleshooting

**TV not found by SSDP scan**
- Verify the TV is on and on the same subnet
- Try adding by IP manually
- On Docker/Linux, set `network_mode: host` in `docker-compose.yml`
- Confirm `http://YOUR_TV_IP:8001/api/v2/` responds in a browser

**Pairing prompt doesn't appear**
- TV must be on and not in standby
- Only one pairing attempt can be in-flight at a time
- Some routers block WebSocket on port 8002

**Images look washed out on the TV**
- Source image uses Adobe RGB or ProPhoto — the pipeline converts automatically; check logs for ICC warnings

**TizenBrew: "Tizen CLI not found"**
- Install Tizen Studio to `~/tizen-studio`
- Or set `TIZEN_CLI_PATH` in `.env` to the full path of the `tizen` binary
- If you have `tizen-extension-platform` on your PATH, set `TIZEN_CLI_PATH` explicitly — extension-platform has no user certificate profiles

**TizenBrew: "Invalid signature / signed with wrong key"**
- Your TV model year is 2022+ (Tizen 7.0) — it requires a DUID-tied Samsung device certificate
- Create a **Samsung** (not Tizen) certificate profile in Tizen Studio Certificate Manager, selecting your TV's DUID
- Use that profile name in `RADARRZEN_TIZEN_PROFILE` / `SONARRZEN_TIZEN_PROFILE`

**Radarrzen: "No TMDB API key injected at build time"**
- Add `TMDB_API_KEY=your_key` to `.env`
- Restart SAWSUBE and reinstall Radarrzen — the key is baked into the WGT at install time

**Schedules not firing**
- Check the schedule is **active**
- Verify time window / day-of-week settings
- Use **Run Now** to test immediately

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python 3.11+), async |
| TV communication | NickWaterton/samsung-tv-ws-api |
| Database | SQLite via SQLAlchemy 2.0 (async) |
| Image processing | Pillow |
| Scheduling | APScheduler 3.x (AsyncIOScheduler) |
| File watching | watchdog |
| Frontend | React 18 + Vite + TypeScript |
| Styling | Tailwind CSS |
| Real-time | FastAPI WebSockets |
| HTTP client | httpx (async) |
| TV sideloading | Tizen Studio CLI (`tizen`, `sdb`) |
| App packaging | WGT (Tizen web app format) |

---

## ☕ Support

Building this took hundreds of hours. If it's saving you money or simplifying your setup:

<a href="https://buymeacoffee.com/succinctrecords"><img src="https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support-yellow?logo=buy-me-a-coffee&style=flat-square&logoColor=black"></a>

---

## License

Personal use / self-hosted. No affiliation with Samsung.
