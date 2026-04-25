
---

# Developer Specification: TizenBrew Integration for SAWSUBE

**Target Model:** Claude Opus 4.5 (claude-opus-4-5)
**Codebase:** [WB2024/SAWSUBE](https://github.com/WB2024/SAWSUBE)
**Reference:** [reisxd/TizenBrew](https://github.com/reisxd/TizenBrew) + [reisxd/TizenBrewInstaller](https://github.com/reisxd/TizenBrewInstaller)
**Date:** April 2026

---

## 1. Overview & Objectives

Integrate a fully guided, point-and-click TizenBrew management experience into SAWSUBE. The user should be able to:

1. Check whether their environment and TV are TizenBrew-ready (health check)
2. Be guided step-by-step through Developer Mode enablement on the TV
3. Automatically detect the TV's Tizen version and determine whether a Samsung Developer Certificate is required
4. If Tizen 7+ is detected, be walked through Samsung account login and certificate creation
5. Install TizenBrew onto the TV with a single button click
6. Browse and install curated or custom TizenBrew-compatible apps from a UI
7. Create and publish custom TizenBrew modules through a form-based UI
8. All operations performed from within SAWSUBE — no terminal required

---

## 2. Codebase Architecture Context (Claude Must Understand This)

### 2.1 SAWSUBE Backend

- **Framework:** FastAPI + Python 3.11+
- **DB:** SQLite via SQLAlchemy async ORM (`aiosqlite`). DB init in `backend/database.py`. All models in `backend/models/`.
- **Entry point:** `backend/main.py`. Routers are registered at the bottom of `main.py` via `app.include_router(...)`.
- **Router pattern:** Each domain has its own file in `backend/routers/` using `APIRouter(prefix="/api/...", tags=[...])`.
- **Service layer:** `backend/services/` — pure Python services. The most relevant is `tv_manager.py` which holds `TVManager` (singleton `tv_manager`) that manages WebSocket connections to TVs via `samsungtvws`.
- **TV Model** (`backend/models/tv.py`): Has `id, name, ip, mac, port, token_path, model, year, last_seen, added_at`. `model` and `year` fields already exist but are **not yet being populated** — this integration should populate them.
- **Config** (`backend/config.py`): Uses `pydantic-settings`. All env vars live here.
- **WebSocket** (`backend/routers/ws.py` + `backend/services/ws_manager.py`): Used for real-time push to frontend. `ws_manager.broadcast(dict)` sends JSON to all connected frontend clients.
- **Requirements:** `backend/requirements.txt` — uses `samsungtvws[async,encrypted] @ git+https://github.com/NickWaterton/samsung-tv-ws-api.git`

### 2.2 SAWSUBE Frontend

- **Framework:** React 18 + TypeScript + Vite + Tailwind CSS v3
- **Router:** `react-router-dom` v6. Routes defined in `frontend/src/App.tsx`.
- **Pages:** `frontend/src/pages/` — `Dashboard.tsx`, `Library.tsx`, `TVControl.tsx`, `Discover.tsx`, `Sources.tsx`, `Schedules.tsx`, `Settings.tsx`.
- **Navigation:** `frontend/src/components/Sidebar.tsx` — the `links` array (line 6) defines all nav items. New page must be added here.
- **API client:** `frontend/src/lib/api.ts` — has an `api` object with `.get()`, `.post()`, `.delete()` etc. All backend calls go through this.
- **WebSocket client:** `frontend/src/lib/ws.ts` — singleton `wsClient`. Hook `useWS(callback)` in `frontend/src/lib/hooks.ts` subscribes to WS messages.
- **Styling:** Uses inline `style={}` with the SAWSUBE palette (`#0F1923` background, `#C8612A` accent, `#F4F1ED` text, `#1E2A35` borders, `#A09890` muted) combined with Tailwind utilities. New components must follow this exact palette and style.
- **State:** Local `useState` / `useEffect` — no Redux or Zustand. Keep this pattern.
- **Toast:** `useToast()` from `frontend/src/components/Toast.tsx` for user feedback.

### 2.3 TizenBrew Architecture (Critical for Implementation)

- **TizenBrew runs ON the TV** as a Tizen Widget App (`.wgt` file).
- **Installation mechanism:** Tizen Studio's CLI tools — `sdb` (Samsung Debug Bridge) and `tizen` — must be installed on the **same machine running SAWSUBE**.
- **Developer Mode on TV is required** before `sdb` can connect. This is done manually on the TV (Apps → `12345` → Enable Developer Mode → Set Host PC IP).
- **sdb port:** TV listens on port `26101` for `sdb` connections.
- **Tizen version detection:** `GET http://<TV_IP>:8001/api/v2/` returns JSON including `device.firmwareVersion`, `device.modelName`, `device.developerMode`, `device.developerIP`. This endpoint is accessible over HTTP (no auth) when Developer Mode is on.
- **Certificate requirement:** Tizen 7+ (2022+ TVs) requires a Samsung Developer Certificate to sign the WGT before install. Earlier versions do not.
- **Samsung Certificate creation:** Requires Samsung account. The Tizen CLI (`tizen certificate -a <alias> -p <password> --samsung ...`) can create a certificate but the Samsung account OAuth step opens a browser. The approach: SAWSUBE backend launches `tizen` CLI with the `--samsung` flag, which triggers browser-based OAuth, and SAWSUBE polls for certificate creation completion.
- **TizenBrew WGT:** Downloaded from `https://github.com/reisxd/TizenBrew/releases/latest` — the asset named `TizenBrewStandalone.wgt`.
- **Module system:** TizenBrew modules are **npm packages** published to npm/jsDelivr. TizenBrew's service fetches them via `https://cdn.jsdelivr.net/<package-name>/...`. The `package.json` of a module includes special fields: `packageType` (`app` | `mods`), `appName`, `appPath` or `websiteURL`, `serviceFile`, `main`, `keys`.
- **Module management within TizenBrew** is handled by TizenBrew's own UI on the TV itself. SAWSUBE **cannot** push module configs directly to TizenBrew's runtime service (it runs on `127.0.0.1:8081` on the TV, not accessible externally).
- **Installing additional apps:** The same `sdb`/`tizen install` pipeline used for TizenBrew can install any other `.wgt` or `.tpk` app on the TV. This is what "installing a TizenBrew app" means in this context — installing the full app package via CLI.
- **Tizen Studio tools paths:** Windows: `C:\tizen-studio\tools\` and `C:\tizen-studio\tools\ide\bin\`. Linux/macOS: `~/tizen-studio/tools/` and `~/tizen-studio/tools/ide/bin/`.

---

## 3. New Files to Create

### 3.1 Backend

```
backend/models/tizenbrew.py          # DB models for TizenBrew state
backend/routers/tizenbrew.py         # All TizenBrew API endpoints
backend/services/tizenbrew_service.py # All TizenBrew business logic
backend/schemas_tizenbrew.py         # Pydantic schemas for TizenBrew
```

### 3.2 Frontend

```
frontend/src/pages/TizenBrew.tsx     # Main TizenBrew page (tabbed)
frontend/src/pages/TizenBrewSetup.tsx    # (sub-component) Setup wizard
frontend/src/pages/TizenBrewApps.tsx     # (sub-component) Browse & install apps
frontend/src/pages/TizenBrewModuleBuilder.tsx  # (sub-component) Custom module builder
```

---

## 4. Database Models

### 4.1 `backend/models/tizenbrew.py`

Create the following SQLAlchemy models:

```python
class TizenBrewState(Base):
    __tablename__ = "tizenbrew_state"
    id: int (primary key)
    tv_id: int (ForeignKey → tvs.id, unique)
    tizen_version: str | None      # e.g. "7.0", "6.0" — parsed from firmware string
    tizen_year: int | None         # e.g. 2022 — derived from model name
    developer_mode_detected: bool  # True if /api/v2/ confirms developerMode == "1"
    sdb_connected: bool            # True if last `sdb devices` showed TV
    tizenbrew_installed: bool      # True if TizenBrew WGT installed successfully
    tizenbrew_version: str | None  # version string from GitHub release
    certificate_profile: str | None  # name of the active Tizen certificate profile
    last_checked: datetime | None
    notes: str | None              # free-text for error messages / status

class TizenBrewInstalledApp(Base):
    __tablename__ = "tizenbrew_installed_apps"
    id: int (primary key)
    tv_id: int (ForeignKey → tvs.id)
    app_name: str
    app_source: str                # "github:user/repo", "wgt:filename", "curated:id"
    installed_at: datetime
    wgt_path: str | None           # local path to .wgt if cached
    version: str | None
```

### 4.2 Register models

In `backend/database.py`, the `init_db()` function calls `Base.metadata.create_all(...)`. The new models must be imported before this is called. Add the import to `backend/main.py` alongside the other model imports so SQLAlchemy picks them up at startup.

---

## 5. Pydantic Schemas

### `backend/schemas_tizenbrew.py`

```python
class TizenInfoResponse(BaseModel):
    tv_id: int
    ip: str
    developer_mode: bool
    developer_ip: str | None
    tizen_version: str | None
    tizen_year: int | None
    model_name: str | None
    requires_certificate: bool     # True if tizen_version >= 7.0

class SdbStatusResponse(BaseModel):
    tv_id: int
    sdb_available: bool            # sdb binary found on PATH/known location
    tizen_available: bool          # tizen binary found
    tv_connected: bool             # TV appeared in `sdb devices`
    error: str | None

class CertificateStatus(BaseModel):
    tv_id: int
    profile_name: str | None
    created: bool
    samsung_account_required: bool
    error: str | None

class InstallProgressEvent(BaseModel):
    type: str                      # "tizenbrew_install_progress"
    tv_id: int
    step: str                      # e.g. "downloading", "connecting", "installing", "done", "error"
    message: str
    progress: int                  # 0-100

class AppDefinition(BaseModel):
    id: str
    name: str
    description: str
    icon_url: str | None
    source_type: str               # "github" | "wgt_url" | "custom"
    source: str                    # e.g. "GlenLowland/jellyfin-tizen-npm-publish" or URL
    category: str                  # e.g. "Media", "Gaming", "Utility"

class CustomModuleCreate(BaseModel):
    package_name: str              # npm package name (kebab-case)
    app_name: str                  # User-friendly name
    package_type: str              # "app" | "mods"
    website_url: str | None        # For mods type
    app_path: str | None           # For app type, e.g. "app/index.html"
    keys: list[str]                # TV remote keys to register
    service_file: str | None       # Optional Node.js service file name
    evaluate_on_start: bool        # evaluateScriptOnDocumentStart
    description: str | None

class ModuleScaffoldResponse(BaseModel):
    package_json: dict             # Generated package.json content
    readme: str                    # Generated README.md content
    instructions: str              # Step-by-step guide for user
```

---

## 6. Backend Service

### `backend/services/tizenbrew_service.py`

This is the core logic layer. All methods are `async`. It must be a class `TizenBrewService` with a singleton instance `tizenbrew_service`.

#### 6.1 Tizen Studio Detection

```python
async def find_tizen_tools() -> dict:
    """
    Search known paths for 'sdb' and 'tizen' binaries.
    Paths to check (in order):
      - System PATH (shutil.which)
      - Windows: C:\tizen-studio\tools\sdb.exe
                 C:\tizen-studio\tools\ide\bin\tizen.bat
      - Linux/macOS: ~/tizen-studio/tools/sdb
                     ~/tizen-studio/tools/ide/bin/tizen
    Returns: { "sdb_path": str|None, "tizen_path": str|None, "found": bool }
    """
```

#### 6.2 TV Info from HTTP API

```python
async def fetch_tv_api_info(tv_ip: str) -> dict:
    """
    GET http://<tv_ip>:8001/api/v2/ with httpx, timeout=5s.
    Parse response JSON. Extract:
      - device.firmwareVersion → parse major Tizen version
      - device.modelName → parse year (e.g. QN65LS03D → 2023)
      - device.developerMode → "1" means enabled
      - device.developerIP → the host IP registered
    Return structured dict. Handle connection errors gracefully.
    
    Tizen version parsing rules:
      - firmwareVersion contains e.g. "T-HKMAKUC-1352.3" — the Tizen version is
        derived from the year: 2022+ = Tizen 7+.
      - More reliable: use modelName year suffix. Samsung model naming:
        Last letter before suffix = year code. A=2014...T=2020, U=2021, B=2022, C=2023, D=2024, E=2025.
        Year codes: T=2020, U=2021, B=2022, C=2023, D=2024, E=2025.
        Map 2022+ (B suffix onward) → requires_certificate = True.
    Return: { "developer_mode": bool, "developer_ip": str, "tizen_version": str,
              "tizen_year": int, "model_name": str, "requires_certificate": bool }
    """
```

#### 6.3 sdb Connection

```python
async def sdb_connect(tv_ip: str, sdb_path: str) -> dict:
    """
    Run: sdb connect <tv_ip>
    Parse output. Returns { "connected": bool, "output": str }
    Timeout: 10 seconds.
    """

async def sdb_devices(sdb_path: str) -> list[str]:
    """
    Run: sdb devices
    Return list of connected device IP strings.
    """
```

#### 6.4 Certificate Management

```python
async def create_samsung_certificate(
    tizen_path: str,
    profile_name: str,
    password: str,
    country: str = "GB",
    state: str = "London",
    city: str = "London",
    org: str = "SAWSUBE",
) -> dict:
    """
    Run: tizen certificate -a <profile_name> -p <password> -c <country>
         -s <state> -ct <city> -o <org> --samsung
    
    This command will open a browser window for Samsung account OAuth.
    The process hangs until the user authenticates in the browser.
    
    Run this in a subprocess with asyncio.create_subprocess_exec.
    Stream stdout/stderr and broadcast progress via ws_manager.
    Timeout: 5 minutes.
    
    Returns: { "success": bool, "profile_name": str, "error": str|None }
    """

async def list_certificate_profiles(tizen_path: str) -> list[str]:
    """
    Run: tizen security-profiles list
    Parse output to return list of profile names.
    """
```

#### 6.5 TizenBrew Installation

```python
async def download_tizenbrew_wgt(download_dir: str) -> dict:
    """
    Use httpx to GET https://api.github.com/repos/reisxd/TizenBrew/releases/latest
    Find asset with name == "TizenBrewStandalone.wgt"
    Download it to download_dir/TizenBrewStandalone.wgt with streaming + progress.
    Broadcast ws_manager events of type "tizenbrew_install_progress" with step="downloading"
    and progress 0-100.
    Returns: { "path": str, "version": str, "error": str|None }
    """

async def resign_wgt(tizen_path: str, wgt_path: str, profile_name: str, output_dir: str) -> dict:
    """
    Run: tizen package -t wgt -s <profile_name> -o <output_dir> -- <wgt_path>
    Required only for Tizen 7+.
    Broadcast progress via ws_manager.
    Returns: { "resigned_path": str|None, "error": str|None }
    """

async def install_wgt(sdb_path: str, tizen_path: str, tv_ip: str, wgt_path: str, tv_id: int) -> dict:
    """
    Steps:
    1. sdb connect <tv_ip> — broadcast step="connecting"
    2. tizen install -n <wgt_path> — broadcast step="installing", stream output
    3. On completion broadcast step="done" or step="error"
    4. Update TizenBrewState in DB: tizenbrew_installed=True, last_checked=now
    Returns: { "success": bool, "output": str, "error": str|None }
    """

async def install_app_wgt(sdb_path: str, tizen_path: str, tv_ip: str, 
                           app_def: dict, tv_id: int, profile_name: str|None) -> dict:
    """
    For installing apps via TizenBrew's installation mechanism.
    If source_type == "github": fetch latest release WGT/TPK from GitHub API
    If source_type == "wgt_url": download from URL
    If profile_name provided: resign before install
    Then install via tizen CLI.
    Returns: { "success": bool, "error": str|None }
    """
```

#### 6.6 Custom Module Scaffolding

```python
def generate_module_scaffold(data: CustomModuleCreate) -> dict:
    """
    Generate package.json content for a TizenBrew module.
    
    For packageType="app":
        {
          "name": data.package_name,
          "version": "1.0.0",
          "packageType": "app",
          "appName": data.app_name,
          "appPath": data.app_path or "app/index.html",
          "keys": data.keys,
          "serviceFile": data.service_file or None,
          "evaluateScriptOnDocumentStart": data.evaluate_on_start,
          "description": data.description or "",
          "main": "app/index.html"
        }
    
    For packageType="mods":
        {
          "name": data.package_name,
          "version": "1.0.0",
          "packageType": "mods",
          "appName": data.app_name,
          "websiteURL": data.website_url,
          "main": "inject.js",
          "keys": data.keys,
          "serviceFile": data.service_file or None,
          "description": data.description or ""
        }
    
    Also generate:
    - README.md with setup instructions
    - Instructions string for the user explaining:
        1. Create an npm account at npmjs.com
        2. Run `npm publish --access public` in your module folder
        3. In TizenBrew on TV, add your package name to install it
    
    Returns: { "package_json": dict, "readme": str, "instructions": str }
    """
```

#### 6.7 Subprocess Helper

```python
async def run_command(cmd: list[str], timeout: float = 60.0, 
                      tv_id: int|None = None, step: str = "") -> dict:
    """
    asyncio.create_subprocess_exec with captured stdout/stderr.
    If tv_id and step provided, broadcast ws_manager events of type
    "tizenbrew_install_progress" as lines stream in.
    Returns: { "returncode": int, "stdout": str, "stderr": str }
    """
```

---

## 7. Backend Router

### `backend/routers/tizenbrew.py`

`APIRouter(prefix="/api/tizenbrew", tags=["tizenbrew"])`

#### Endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/tools` | Check if sdb/tizen binaries are found |
| `GET` | `/{tv_id}/info` | Fetch TV info from port 8001 API, detect Tizen version, update DB |
| `GET` | `/{tv_id}/status` | Return full TizenBrewState for TV from DB |
| `POST` | `/{tv_id}/sdb-connect` | Run `sdb connect <tv_ip>` |
| `GET` | `/{tv_id}/sdb-devices` | Run `sdb devices`, return list |
| `GET` | `/certificates` | List certificate profiles |
| `POST` | `/{tv_id}/certificate` | Body: `{ profile_name, password, country }` — create Samsung cert. Long-running — immediately returns `{ "started": true }`, progress streamed via WS. |
| `POST` | `/{tv_id}/install-tizenbrew` | Download + resign (if needed) + install TizenBrew WGT. Long-running, progress via WS. Returns `{ "started": true }` immediately. |
| `GET` | `/apps` | Return curated app list (hardcoded in service) |
| `POST` | `/{tv_id}/install-app` | Body: `AppDefinition` — download + install app WGT. Progress via WS. |
| `GET` | `/{tv_id}/installed-apps` | List installed apps from DB |
| `POST` | `/module/scaffold` | Body: `CustomModuleCreate` — return generated scaffold files |

#### Important implementation note for long-running endpoints:
Long-running operations (certificate creation, installs) must:
1. Return `{ "started": true, "job_id": str }` immediately (HTTP 202)
2. Run the actual work in `asyncio.create_task(...)` in the background
3. Push progress events to `ws_manager.broadcast({"type": "tizenbrew_install_progress", "tv_id": ..., "step": ..., "message": ..., "progress": 0-100})`
4. Store final result in `TizenBrewState.notes` in DB

---

## 8. Register Router in main.py

In `backend/main.py`, add:

```python
from .routers import tizenbrew as tizenbrew_router
# ... after existing include_router calls:
app.include_router(tizenbrew_router.router)
```

Also import the new models so SQLAlchemy creates the tables:
```python
from .models import tizenbrew  # noqa — imported for side-effect (table creation)
```

---

## 9. TV Model Enhancement

In `backend/routers/tv.py`, the existing `GET /{tv_id}/info` endpoint calls `tv_manager.device_info()`. When TizenBrew info is fetched, **also update** `tv.model` and `tv.year` in the DB using data returned from the port 8001 API if they are currently `None`.

In `backend/services/tizenbrew_service.py`, after calling `fetch_tv_api_info()`, update the TV row:
```python
async with SessionLocal() as s:
    tv = await s.get(TV, tv_id)
    if tv and not tv.model:
        tv.model = info["model_name"]
        tv.year = str(info["tizen_year"])
        await s.commit()
```

---

## 10. Frontend Page

### `frontend/src/pages/TizenBrew.tsx`

This is a **single tabbed page** with three tabs: **Setup**, **Apps**, and **Module Builder**.

The page must:
- Use the existing SAWSUBE colour palette exactly (`#0F1923`, `#C8612A`, `#F4F1ED`, `#1E2A35`, `#4A7C5F`, `#A33228`, `#C49A3C`)
- Follow the same code patterns as `TVControl.tsx` and `Settings.tsx`
- Use `useToast()` for notifications
- Use `useWS()` to listen for `tizenbrew_install_progress` events and show live progress
- Use the `api` client from `../lib/api`

#### 10.1 Tab: Setup

This is a **vertical wizard** with numbered steps. Each step has a status indicator (✅ green / ⚠️ amber / ❌ red / ⏳ pending). Steps are sequential — each is only actionable once the previous is complete.

**Step 1 — Tizen Studio Tools**
- On load, call `GET /api/tizenbrew/tools`
- Show: ✅ "Tizen Studio found" or ❌ "Not found"
- If not found: show a box with instructions:
  - Link to `https://developer.samsung.com/smarttv/develop/getting-started/setting-up-sdk/installing-tv-sdk.html`
  - Text: "Install Tizen Studio, then click Refresh"
  - Button: **Refresh** (re-calls the endpoint)
- Show which TV is selected (dropdown if multiple TVs — populated from `GET /api/tvs`)

**Step 2 — TV Selection & Developer Mode**
- Select TV from dropdown (maps to existing SAWSUBE TVs)
- Show Developer Mode status — call `GET /api/tizenbrew/{tv_id}/info`
- If `developer_mode == false`: show step-by-step instructions in a styled box:
  1. On your Samsung TV remote, press **Home**
  2. Open **Apps**
  3. Using your remote, type **12345** on the numeric input (do NOT press Enter)
  4. A Developer Mode dialog appears — toggle **Developer Mode** to **On**
  5. Enter your PC's IP address in the **Host PC IP** field: `{auto-detected or input field}`
  6. Press **OK** and **reboot your TV**
  7. After reboot, click **Check Again** below
- Button: **Check Again** → re-calls `GET /api/tizenbrew/{tv_id}/info`
- If detected: show ✅ green tick, Tizen version badge, and model name

**Step 3 — Connect via sdb**
- Show current sdb connection status
- Button: **Connect TV** → calls `POST /api/tizenbrew/{tv_id}/sdb-connect`
- Show result inline (success / error message)
- After success: ✅ "TV connected via sdb"

**Step 4 — Samsung Certificate (conditional)**
- **Only shown** if `requires_certificate == true` (Tizen 7+)
- Check existing certificates via `GET /api/tizenbrew/certificates`
- If a profile exists: show ✅ "Certificate ready — {profile_name}"
- If no certificate: show an orange info banner:
  > "Your TV runs Tizen 7+ (2022 or newer). Samsung requires a developer certificate to install apps. This will open a browser window for Samsung account sign-in."
- Form fields: **Profile Name** (default: "SAWSUBE"), **Password** (input type password), **Country** (default: GB)
- Button: **Create Certificate & Sign In with Samsung** → calls `POST /api/tizenbrew/{tv_id}/certificate`
- Show a live terminal-style log box (dark background, monospace font) fed by `tizenbrew_install_progress` WS events
- Info note: "A browser window will open — sign in to your Samsung account to complete certificate creation"
- On done: ✅ "Certificate created"

**Step 5 — Install TizenBrew**
- Show current install status from `GET /api/tizenbrew/{tv_id}/status`
- If already installed: show ✅ "TizenBrew {version} installed" with a **Re-install** button
- If not installed: Button: **Install TizenBrew** → calls `POST /api/tizenbrew/{tv_id}/install-tizenbrew`
- Show live progress bar (0–100%) and log box fed by WS `tizenbrew_install_progress` events
- Steps shown in log: "⬇️ Downloading TizenBrew WGT...", "✍️ Signing with certificate...", "📺 Installing on TV...", "✅ Done!"
- On error: show red error box with the error message and a **Retry** button
- On success: confetti (simple CSS animation) + "🎉 TizenBrew installed! Launch it from your TV's app list."

#### 10.2 Tab: Apps

A grid of installable apps. Each card shows: icon, name, description, category badge, source label.

**Curated App List** (hardcoded in `tizenbrew_service.py`, returned by `GET /api/tizenbrew/apps`):

| App | Source | Category |
|-----|--------|----------|
| TizenTube | `github:reisxd/TizenTube` | Entertainment |
| Jellyfin | `github:GlenLowland/jellyfin-tizen-npm-publish` | Media |
| Moonlight | `github:ndriqimlahu/moonlight-tizen` | Gaming |

Each app card:
- Thumbnail/icon (use a placeholder icon if none available)
- Name + description
- Category badge (pill)
- **Install** button → calls `POST /api/tizenbrew/{tv_id}/install-app` with the `AppDefinition`
- Shows live progress in a modal or inline via WS events
- If already in `TizenBrewInstalledApp` DB table: show ✅ "Installed" badge instead

**Custom Install section** (below the grid):
- Heading: "Install Custom App"
- Sub-heading: "Enter a GitHub repo (format: `user/repo`) or a direct `.wgt` / `.tpk` URL"
- Input field + dropdown for type (GitHub / URL)
- **Install** button

**Installed Apps section** (collapsible):
- List from `GET /api/tizenbrew/{tv_id}/installed-apps`
- Shows name, installed date, source

#### 10.3 Tab: Module Builder

A form-based TizenBrew module scaffolder.

**Form fields:**

| Field | Type | Notes |
|-------|------|-------|
| Module Type | Radio/Select | "App Module" or "Site Modification" |
| Package Name | text | npm package name, enforced kebab-case, auto-lowercase |
| App Name | text | User-friendly display name |
| Website URL | text | Only shown if type = "Site Modification" |
| App Entry Path | text | Default "app/index.html". Only shown if type = "App" |
| TV Remote Keys | multi-select | List of common Samsung remote keys: `MediaPlayPause`, `MediaFastForward`, `MediaRewind`, `ColorF0Red`, `ColorF1Green`, `ColorF2Yellow`, `ColorF3Blue`, `0-9` |
| Include Service Worker | checkbox | Adds `serviceFile: "service.js"` |
| Evaluate on Page Start | checkbox | `evaluateScriptOnDocumentStart`. Only shown for Site Modification |
| Description | textarea | |

**Button: Generate Module Scaffold** → calls `POST /api/tizenbrew/module/scaffold`

**Output section** (shown after response):
- Tabbed display of generated files:
  - `package.json` — syntax-highlighted JSON in a code block (dark background, monospace)
  - `README.md` — rendered markdown preview
- **Copy to Clipboard** button for each file
- **Download as ZIP** button — uses `JSZip` (must add to `package.json` devDependencies) to package the files and trigger browser download
- **Instructions panel** — displays the step-by-step guide from `instructions` field: how to publish to npm and add to TizenBrew on TV

---

## 11. Sidebar Navigation Update

In `frontend/src/components/Sidebar.tsx`, add to the `links` array (after `Settings`):

```tsx
['/tizenbrew', 'TizenBrew'],
```

The new route must also be registered in `frontend/src/App.tsx`:

```tsx
import TizenBrew from './pages/TizenBrew'
// ...
<Route path="/tizenbrew" element={<TizenBrew />} />
```

---

## 12. WebSocket Event Types

New WS event types (sent backend → frontend via `ws_manager.broadcast()`):

```json
{
  "type": "tizenbrew_install_progress",
  "tv_id": 1,
  "step": "downloading|connecting|resigning|installing|done|error",
  "message": "Human-readable status message",
  "progress": 45
}
```

Frontend `useWS()` in `TizenBrew.tsx` must handle this event type and update a `progressState` local state.

---

## 13. Config Additions

In `backend/config.py`, add to `Settings`:

```python
TIZENBREW_DOWNLOAD_DIR: str = "./data/tizenbrew"
TIZEN_SDB_PATH: str = ""      # Override auto-detected sdb path
TIZEN_CLI_PATH: str = ""      # Override auto-detected tizen path
```

In `backend/config.py` `init` section at bottom, ensure `TIZENBREW_DOWNLOAD_DIR` directory is created:
```python
Path(settings.TIZENBREW_DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
```

---

## 14. Dependencies

### Backend additions to `backend/requirements.txt`:
No new dependencies needed — `httpx` and `asyncio` subprocesses are already available.

### Frontend additions to `frontend/package.json`:
```json
"jszip": "^3.10.1"
```
(For the "Download as ZIP" feature in the Module Builder tab)

---

## 15. Error Handling Requirements

- **All subprocess calls** must have timeouts. If a command exceeds its timeout, broadcast a `step="error"` WS event and return an error dict. Never let a subprocess hang indefinitely.
- **TV unreachable** (port 8001): return a structured error explaining Developer Mode is likely not enabled yet, not a generic 500.
- **sdb not found**: return a clear error message pointing to Tizen Studio installation, not a generic 500.
- **Certificate failure**: If the Samsung OAuth browser flow fails or times out (5 min), broadcast error and provide retry guidance.
- **WGT download failure**: Fall back gracefully with error message, do not leave partial files.
- All backend endpoints must return `HTTPException` with descriptive `detail` strings (not bare Python exceptions).
- Frontend must catch API errors and show them via `useToast()` with an error style, never swallow them silently.

---

## 16. Key Technical Constraints & Notes for Claude

1. **Do not use `subprocess.run()` (blocking).** All subprocess calls must use `asyncio.create_subprocess_exec()` with `await proc.wait()` to avoid blocking the FastAPI event loop.

2. **The TizenBrew service on the TV (port 8081) is NOT accessible from SAWSUBE.** Do not attempt to communicate with it. All TizenBrew management from SAWSUBE is purely via `sdb`/`tizen` CLI tools.

3. **The TV model `TV` already has `model` and `year` fields** — use them. Don't add new columns for this.

4. **sdb connection to the TV requires Developer Mode to be on and the Host PC IP to be set to the SAWSUBE server's IP on the TV.** The info endpoint at port 8001 will confirm `developerIP` — if it doesn't match the server IP, show a warning.

5. **Samsung model year parsing:** The model name suffix letter indicates year. The mapping is: `T`=2020, `U`=2021, `B`=2022, `C`=2023, `D`=2024, `E`=2025. The last uppercase letter before any trailing digits/suffix in the model name is the year code. Models with year 2022+ (suffix B or later) require Samsung certificate.

6. **Tizen Studio is a prerequisite that SAWSUBE cannot install automatically** — it is a multi-GB IDE. Clearly communicate this to the user with a link, never try to download it programmatically.

7. **Certificate creation opens a browser** — this is unavoidable. The SAWSUBE backend must launch the `tizen certificate` command and stream its output while waiting. Do not try to automate the browser OAuth.

8. **For the curated apps list** — sourcing the WGT for GitHub-type apps: use `GET https://api.github.com/repos/{owner}/{repo}/releases/latest` and find the first asset ending in `.wgt` or `.tpk`. If no release asset found, fall back to the source repo URL with a manual instruction.

9. **Keep the SAWSUBE style exactly.** No new CSS frameworks, no new component libraries. Use inline `style={}` objects with the SAWSUBE colour palette and Tailwind utility classes exactly as done in `TVControl.tsx` and `Settings.tsx`.

10. **Follow existing patterns exactly:**
    - Backend: `router = APIRouter(prefix=...)`, `Depends(get_session)`, SQLAlchemy async session
    - Frontend: `useState` + `useEffect`, `api.get<Type>(...)`, `useToast()`, `useWS()`

---

## 17. File Change Summary

| File | Action | Notes |
|------|--------|-------|
| `backend/models/tizenbrew.py` | **CREATE** | Two new DB models |
| `backend/schemas_tizenbrew.py` | **CREATE** | All Pydantic schemas |
| `backend/services/tizenbrew_service.py` | **CREATE** | All business logic |
| `backend/routers/tizenbrew.py` | **CREATE** | API endpoints |
| `backend/main.py` | **MODIFY** | Register router + import models |
| `backend/config.py` | **MODIFY** | Add 3 new config fields |
| `frontend/src/pages/TizenBrew.tsx` | **CREATE** | Full tabbed page |
| `frontend/src/App.tsx` | **MODIFY** | Add route |
| `frontend/src/components/Sidebar.tsx` | **MODIFY** | Add nav link |
| `frontend/package.json` | **MODIFY** | Add `jszip` dependency |

---