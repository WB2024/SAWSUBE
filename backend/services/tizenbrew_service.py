from __future__ import annotations
import asyncio
import json
import logging
import os
import platform
import re
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from ..config import settings
from ..database import SessionLocal
from ..models.tv import TV
from ..models.tizenbrew import TizenBrewState, TizenBrewInstalledApp
from ..schemas_tizenbrew import CustomModuleCreate
from .ws_manager import ws_manager

log = logging.getLogger(__name__)


# Samsung TV model-name year-code mapping (last uppercase letter before any
# trailing region/series digits represents the model year).
YEAR_CODE_MAP: dict[str, int] = {
    "H": 2014, "J": 2015, "K": 2016, "M": 2017, "N": 2018,
    "R": 2019, "T": 2020, "U": 2021, "B": 2022, "C": 2023,
    "D": 2024, "E": 2025, "F": 2026,
}

# 2022+ TVs require a Samsung developer certificate
CERT_REQUIRED_FROM_YEAR = 2022


CURATED_APPS: list[dict[str, Any]] = [
    {
        "id": "tizentube",
        "name": "TizenTube",
        "description": "Ad-free YouTube for Samsung TVs. Installed via TizenBrew on your TV — open TizenBrew and find it in the store.",
        "icon_url": "https://raw.githubusercontent.com/reisxd/TizenTube/main/icon.png",
        "source_type": "tizenbrew",
        "source": "TizenTube",
        "category": "Entertainment",
    },
    {
        "id": "jellyfin",
        "name": "Jellyfin",
        "description": "Free Software Media System — your own personal Netflix. Daily-built WGT from jeppevinkel/jellyfin-tizen-builds.",
        "icon_url": "https://raw.githubusercontent.com/jellyfin/jellyfin-ux/master/branding/SVG/icon-transparent.svg",
        "source_type": "github",
        "source": "jeppevinkel/jellyfin-tizen-builds",
        "category": "Media",
    },
    {
        "id": "moonlight",
        "name": "Moonlight",
        "description": "Stream PC games to your TV via NVIDIA GameStream / Sunshine.",
        "icon_url": "https://raw.githubusercontent.com/moonlight-stream/moonlight-stream.github.io/master/resources/Moonlight.svg",
        "source_type": "github",
        "source": "brightcraft/moonlight-tizen",
        "category": "Gaming",
    },
    {
        "id": "radarr",
        "name": "Radarrzen",
        "description": "Movie collection manager for your Samsung TV. Connects to your existing Radarr instance — browse your library, search for movies, and monitor downloads from your couch.",
        "icon_url": "https://raw.githubusercontent.com/Radarr/Radarr/develop/Logo/256.png",
        "source_type": "local_build",
        "source": "local:radarrzen",
        "category": "Media",
        "inject_config": {
            "storage_key": "radarrzen-config",
            "config_file": "js/sawsube-config.js",
            "fields": {"url": "RADARR_URL", "apiKey": "RADARR_API_KEY", "sawsubeUrl": "SAWSUBE_URL"},
        },
    },
    {
        "id": "sonarr",
        "name": "Sonarrzen",
        "description": "TV-show collection manager for your Samsung TV. Connects to your existing Sonarr instance — browse your library, search for shows, manage seasons & episodes, and monitor downloads from your couch.",
        "icon_url": "https://raw.githubusercontent.com/Sonarr/Sonarr/develop/Logo/256.png",
        "source_type": "local_build",
        "source": "local:sonarrzen",
        "category": "Media",
        "inject_config": {
            "storage_key": "sonarrzen-config",
            "config_file": "js/sawsube-config.js",
            "fields": {"url": "SONARR_URL", "apiKey": "SONARR_API_KEY", "sawsubeUrl": "SAWSUBE_URL"},
        },
    },
    {
        "id": "fieshzen",
        "name": "Fieshzen",
        "description": "Full-featured music player for your Samsung TV. Connects to your Navidrome (or OpenSubsonic-compatible) server — browse albums, artists, playlists, view lyrics, and listen to your music collection from your couch.",
        "icon_url": "https://raw.githubusercontent.com/jeffvli/feishin/main/resources/icons/icon.png",
        "source_type": "local_build",
        "source": "local:fieshzen",
        "category": "Music",
    },
    {
        "id": "castafiorezen",
        "name": "Castafiorezen",
        "description": "Native Tizen music player for Navidrome / Subsonic — built from scratch in ES5 for Samsung TVs. Lightweight, remote-friendly, AVPlay-backed audio.",
        "icon_url": "https://raw.githubusercontent.com/jeffvli/feishin/main/resources/icons/icon.png",
        "source_type": "local_build",
        "source": "local:castafiorezen",
        "category": "Music",
        "inject_config": {
            "storage_key": "cz-server",
            "config_file": "js/sawsube-config.js",
            "fields": {
                "serverUrl": "NAVIDROME_URL",
                "username": "NAVIDROME_USERNAME",
                "password": "NAVIDROME_PASSWORD",
            },
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def parse_year_from_model(model_name: str | None) -> int | None:
    """Extract year from a Samsung model name like 'QN65LS03DAFXZA'."""
    if not model_name:
        return None
    # Find letter codes between digits — pattern '<digits><LETTERS><digits>'
    # The year code is typically the last uppercase letter group's first letter.
    candidates = re.findall(r"[A-Z]+", model_name)
    for grp in reversed(candidates):
        for ch in grp:
            if ch in YEAR_CODE_MAP:
                return YEAR_CODE_MAP[ch]
    return None


def tizen_version_from_year(year: int | None) -> str | None:
    """Approximate Tizen OS version from TV year (mass-market mapping)."""
    if not year:
        return None
    table = {
        2017: "3.0", 2018: "4.0", 2019: "5.0", 2020: "5.5",
        2021: "6.0", 2022: "7.0", 2023: "7.0", 2024: "8.0", 2025: "9.0",
        2026: "9.0",
    }
    return table.get(year)


def requires_certificate(year: int | None) -> bool:
    return bool(year and year >= CERT_REQUIRED_FROM_YEAR)


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────

class TizenBrewService:
    def __init__(self) -> None:
        self.download_dir = Path(getattr(settings, "TIZENBREW_DOWNLOAD_DIR", "./data/tizenbrew"))
        self.download_dir.mkdir(parents=True, exist_ok=True)
        # Track running jobs by tv_id to prevent overlap
        self._jobs: dict[int, asyncio.Task] = {}

    # ── Tool detection ─────────────────────────────────────────────────────
    async def find_tizen_tools(self) -> dict[str, Any]:
        sdb_override = getattr(settings, "TIZEN_SDB_PATH", "") or ""
        tizen_override = getattr(settings, "TIZEN_CLI_PATH", "") or ""

        sdb_path: str | None = None
        tizen_path: str | None = None

        # Explicit .env overrides take priority (must point to the file)
        if sdb_override and Path(sdb_override).is_file():
            sdb_path = sdb_override
        if tizen_override and Path(tizen_override).is_file():
            tizen_path = tizen_override

        # Well-known installation directories (checked before shutil.which so that
        # tizen-studio is preferred over whatever binary happens to be on PATH,
        # e.g. tizen-extension-platform which has no user profiles)
        candidate_roots: list[Path] = []
        if platform.system() == "Windows":
            candidate_roots += [Path("C:/tizen-studio"), Path("C:/tizen-studio-data")]
            sdb_name = "sdb.exe"
            tizen_name = "tizen.bat"
        else:
            home = Path.home()
            candidate_roots += [home / "tizen-studio", Path("/opt/tizen-studio"), Path("/usr/local/tizen-studio")]
            sdb_name = "sdb"
            tizen_name = "tizen"

        for root in candidate_roots:
            if not sdb_path:
                p = root / "tools" / sdb_name
                if p.is_file():
                    sdb_path = str(p)
            if not tizen_path:
                p = root / "tools" / "ide" / "bin" / tizen_name
                if p.is_file():
                    tizen_path = str(p)

        # Last resort: whatever is on PATH
        if not sdb_path:
            sdb_path = shutil.which("sdb")
        if not tizen_path:
            tizen_path = shutil.which("tizen")

        return {
            "sdb_path": sdb_path,
            "tizen_path": tizen_path,
            "found": bool(sdb_path and tizen_path),
        }


    # ── TV info via port 8001 ─────────────────────────────────────────────
    async def fetch_tv_api_info(self, tv_ip: str) -> dict[str, Any]:
        url = f"http://{tv_ip}:8001/api/v2/"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            return {
                "error": f"TV API unreachable at {url}: {e}. Is Developer Mode enabled?",
                "developer_mode": False,
                "developer_ip": None,
                "tizen_version": None,
                "tizen_year": None,
                "model_name": None,
                "requires_certificate": False,
            }

        device = data.get("device", {}) if isinstance(data, dict) else {}
        model_name = device.get("modelName") or device.get("model")
        firmware = device.get("firmwareVersion") or ""
        dev_mode_raw = str(device.get("developerMode", "0"))
        dev_mode = dev_mode_raw in ("1", "true", "True")
        dev_ip = device.get("developerIP") or None

        year = parse_year_from_model(model_name)
        tv_ver = tizen_version_from_year(year)

        return {
            "error": None,
            "developer_mode": dev_mode,
            "developer_ip": dev_ip,
            "tizen_version": tv_ver,
            "tizen_year": year,
            "model_name": model_name,
            "firmware": firmware,
            "requires_certificate": requires_certificate(year),
        }

    # ── DB state helpers ───────────────────────────────────────────────────
    async def get_or_create_state(self, tv_id: int) -> TizenBrewState:
        async with SessionLocal() as s:
            row = (await s.execute(
                select(TizenBrewState).where(TizenBrewState.tv_id == tv_id)
            )).scalar_one_or_none()
            if row:
                return row
            row = TizenBrewState(tv_id=tv_id)
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return row

    async def update_state(self, tv_id: int, **fields: Any) -> TizenBrewState:
        async with SessionLocal() as s:
            row = (await s.execute(
                select(TizenBrewState).where(TizenBrewState.tv_id == tv_id)
            )).scalar_one_or_none()
            if not row:
                row = TizenBrewState(tv_id=tv_id)
                s.add(row)
            for k, v in fields.items():
                setattr(row, k, v)
            row.last_checked = datetime.utcnow()
            await s.commit()
            await s.refresh(row)
            return row

    async def update_tv_model_year(self, tv_id: int, model_name: str | None, year: int | None) -> None:
        if not model_name and not year:
            return
        async with SessionLocal() as s:
            tv = await s.get(TV, tv_id)
            if not tv:
                return
            changed = False
            if model_name and not tv.model:
                tv.model = model_name
                changed = True
            if year and not tv.year:
                tv.year = str(year)
                changed = True
            if changed:
                await s.commit()

    # ── Subprocess runner with WS streaming ────────────────────────────────
    async def run_command(
        self,
        cmd: list[str],
        timeout: float = 120.0,
        tv_id: int | None = None,
        step: str = "",
        progress: int = 0,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        log.info("tizenbrew: running %s", " ".join(cmd))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )
        except FileNotFoundError as e:
            return {"returncode": -1, "stdout": "", "stderr": str(e), "error": str(e)}

        out_lines: list[str] = []

        async def _read() -> None:
            assert proc.stdout
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                if not text:
                    continue
                out_lines.append(text)
                if tv_id is not None and step:
                    await ws_manager.broadcast({
                        "type": "tizenbrew_install_progress",
                        "tv_id": tv_id,
                        "step": step,
                        "message": text,
                        "progress": progress,
                    })

        try:
            await asyncio.wait_for(asyncio.gather(_read(), proc.wait()), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            err = f"Command timed out after {timeout}s"
            if tv_id is not None:
                await ws_manager.broadcast({
                    "type": "tizenbrew_install_progress",
                    "tv_id": tv_id, "step": "error",
                    "message": err, "progress": 0,
                })
            return {"returncode": -1, "stdout": "\n".join(out_lines), "stderr": err, "error": err}

        return {
            "returncode": proc.returncode or 0,
            "stdout": "\n".join(out_lines),
            "stderr": "",
            "error": None,
        }

    # ── sdb ────────────────────────────────────────────────────────────────
    async def sdb_connect(self, tv_ip: str, sdb_path: str) -> dict[str, Any]:
        res = await self.run_command([sdb_path, "connect", tv_ip], timeout=30.0)
        out = res["stdout"].lower()
        connected = "connected" in out and "fail" not in out and "unable" not in out
        return {"connected": connected, "output": res["stdout"], "error": res.get("error")}

    async def sdb_devices(self, sdb_path: str) -> list[str]:
        res = await self.run_command([sdb_path, "devices"], timeout=10.0)
        ips: list[str] = []
        for line in res["stdout"].splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices") or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] in ("device", "online"):
                ips.append(parts[0])
        return ips

    # ── Certificates ───────────────────────────────────────────────────────
    async def list_certificate_profiles(self, tizen_path: str) -> list[str]:
        res = await self.run_command([tizen_path, "security-profiles", "list"], timeout=15.0)
        names: list[str] = []
        for line in res["stdout"].splitlines():
            m = re.match(r"^\s*([A-Za-z0-9_\-]+)\s*:", line)
            if m and m.group(1).lower() not in ("name", "profile", "profiles"):
                names.append(m.group(1))
            else:
                m2 = re.match(r"^\s*Name\s*:\s*(\S+)", line)
                if m2:
                    names.append(m2.group(1))
        # de-dup, keep order
        seen = set()
        out = []
        for n in names:
            if n not in seen:
                seen.add(n)
                out.append(n)
        return out

    async def create_samsung_certificate(
        self,
        tizen_path: str,
        profile_name: str,
        password: str,
        country: str = "GB",
        state: str = "London",
        city: str = "London",
        org: str = "SAWSUBE",
        tv_id: int | None = None,
    ) -> dict[str, Any]:
        """Create a developer certificate + security profile via tizen CLI.

        Uses `tizen certificate` with standard flags only (-a, -p, -o, -s, -u).
        The --samsung flag requires the Samsung Certificate Extension which is
        not installed by default; we skip it entirely.  A standard developer
        certificate is sufficient for sideloading WGT apps on Samsung TVs.
        """
        async def _broadcast(msg: str, pct: int, step: str = "certificate") -> None:
            if tv_id is not None:
                await ws_manager.broadcast({
                    "type": "tizenbrew_install_progress", "tv_id": tv_id,
                    "step": step, "progress": pct, "message": msg,
                })

        await _broadcast("Creating developer certificate…", 5)

        # tizen CLI stores certs at ~/tizen-studio-data/keystore/author/<alias>.p12.
        # If the file already exists the CLI refuses ("Already exist the specified
        # filename") — skip certificate creation and reuse the existing .p12.
        keystore_p12 = Path.home() / "tizen-studio-data" / "keystore" / "author" / f"{profile_name}.p12"
        already_exists = keystore_p12.exists()

        if already_exists:
            await _broadcast(f"Reusing existing certificate '{profile_name}'…", 40)
            res = {"returncode": 0, "stdout": "", "stderr": ""}
        else:
            # Use only flags that exist in all Tizen Studio CLI versions.
            # -a  alias / output file name (required in older SDKs)
            # -p  password (always required)
            # -o  organization
            # -s  state
            # -u  org unit (we reuse as city; it's optional)
            cert_cmd = [
                tizen_path, "certificate",
                "-a", profile_name,
                "-p", password,
                "-o", org,
                "-s", state,
                "-u", city,
            ]

            await _broadcast("Running tizen certificate…", 20)
            res = await self.run_command(
                cert_cmd, timeout=60.0, tv_id=tv_id, step="certificate", progress=50,
            )

            # Detect failure by help-text in output (tizen prints help on bad args)
            out_lower = res["stdout"].lower()
            help_printed = (
                "specify the user" in out_lower
                or "usage:" in out_lower
                or "--help" in out_lower
                or ("returncode" in res and res["returncode"] != 0 and "-p (--password)" in out_lower)
            )
            if help_printed and res["returncode"] != 0:
                # Try with only the truly required flag to isolate the issue
                await _broadcast("Retrying with minimal flags…", 30)
                cert_cmd_min = [tizen_path, "certificate", "-p", password]
                res = await self.run_command(
                    cert_cmd_min, timeout=60.0, tv_id=tv_id, step="certificate", progress=55,
                )

        success = res["returncode"] == 0

        if success:
            await _broadcast("Registering security profile…", 80)
            # tizen CLI places the p12 at ~/tizen-studio-data/keystore/author/<alias>.p12
            # (standard developer cert).  SamsungCertificate/<alias>/ is only used when
            # the Samsung Certificate Extension is installed.  Try both, plus fallbacks.
            home = Path.home()
            samsung_cert_dir = home / "SamsungCertificate" / profile_name
            p12_candidates = [
                keystore_p12,  # ~/tizen-studio-data/keystore/author/<alias>.p12 (standard)
                samsung_cert_dir / f"{profile_name}.p12",
                self.download_dir / f"{profile_name}.p12",
                Path.cwd() / f"{profile_name}.p12",
            ]
            p12_path = next((p for p in p12_candidates if p.exists()), p12_candidates[0])

            profile_cmd = [
                tizen_path, "security-profiles", "add",
                "-n", profile_name,
                "-a", str(p12_path),
                "-p", password,
            ]
            await self.run_command(profile_cmd, timeout=30.0, tv_id=tv_id, step="certificate", progress=90)
            await _broadcast("✓ Certificate + profile created", 100)
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id or 0,
                "step": "done", "progress": 100,
                "message": f"Certificate '{profile_name}' created successfully",
            })
            if tv_id is not None:
                await self.update_state(tv_id, certificate_profile=profile_name)
        else:
            err = res.get("stderr") or res.get("error") or "tizen certificate failed — see log above"
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id or 0,
                "step": "error", "progress": 0,
                "message": f"Certificate failed: {err}",
            })

        return {
            "success": success,
            "profile_name": profile_name if success else None,
            "error": None if success else (res.get("stderr") or res.get("error") or "tizen certificate failed"),
        }

    # ── TizenBrew download / install ───────────────────────────────────────
    async def download_tizenbrew_wgt(self, tv_id: int | None = None) -> dict[str, Any]:
        api_url = "https://api.github.com/repos/reisxd/TizenBrew/releases/latest"
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                r = await client.get(api_url, headers={"Accept": "application/vnd.github+json"})
                r.raise_for_status()
                rel = r.json()
                version = rel.get("tag_name") or rel.get("name") or "latest"
                asset = next(
                    (a for a in rel.get("assets", []) if a.get("name", "").lower().endswith(".wgt")),
                    None,
                )
                if not asset:
                    return {"path": None, "version": None, "error": "No .wgt asset found in latest release"}
                dl_url = asset["browser_download_url"]
                size = int(asset.get("size") or 0)

                target = self.download_dir / asset["name"]
                if tv_id is not None:
                    await ws_manager.broadcast({
                        "type": "tizenbrew_install_progress", "tv_id": tv_id,
                        "step": "downloading", "progress": 5,
                        "message": f"Downloading {asset['name']} ({size // 1024} KB)…",
                    })
                async with client.stream("GET", dl_url) as resp:
                    resp.raise_for_status()
                    written = 0
                    last_pct = 0
                    with open(target, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                            f.write(chunk)
                            written += len(chunk)
                            if size and tv_id is not None:
                                pct = min(40, int(written * 40 / size))
                                if pct - last_pct >= 5:
                                    last_pct = pct
                                    await ws_manager.broadcast({
                                        "type": "tizenbrew_install_progress", "tv_id": tv_id,
                                        "step": "downloading", "progress": pct,
                                        "message": f"Downloaded {written // 1024} KB",
                                    })
                if tv_id is not None:
                    await ws_manager.broadcast({
                        "type": "tizenbrew_install_progress", "tv_id": tv_id,
                        "step": "downloading", "progress": 40,
                        "message": "Download complete",
                    })
                return {"path": str(target), "version": version, "error": None}
        except Exception as e:
            log.exception("tizenbrew download failed")
            if tv_id is not None:
                await ws_manager.broadcast({
                    "type": "tizenbrew_install_progress", "tv_id": tv_id,
                    "step": "error", "progress": 0,
                    "message": f"Download failed: {e}",
                })
            return {"path": None, "version": None, "error": str(e)}

    async def inject_app_config(self, app_def: dict[str, Any], wgt_path: str, tv_id: int | None = None) -> str:
        """
        If app_def has inject_config, read values from settings and write a
        pre-seed JS file into the WGT before it gets re-signed.  The WGT on
        GitHub stays credential-free; credentials are injected locally only.
        Returns the (possibly new) wgt_path.
        """
        import zipfile
        import tempfile
        import json as _json

        inject_cfg = app_def.get("inject_config")
        if not inject_cfg:
            log.info("inject_app_config: no inject_config for app '%s', skipping", app_def.get("id"))
            return wgt_path

        storage_key: str = inject_cfg["storage_key"]
        config_file: str = inject_cfg.get("config_file", "js/sawsube-config.js")
        fields: dict[str, str] = inject_cfg.get("fields", {})

        config: dict[str, str] = {}
        for js_key, settings_attr in fields.items():
            val = getattr(settings, settings_attr, "") or ""
            if val:
                config[js_key] = val

        log.info("inject_app_config: app='%s' fields=%s values_found=%s",
                 app_def.get("id"), list(fields.keys()), list(config.keys()))

        if tv_id is not None:
            preview = {k: (v[:8] + "…" if k == "apiKey" and len(v) > 8 else v)
                       for k, v in config.items()}
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id,
                "step": "injecting", "progress": 35,
                "message": f"Injecting config into WGT: {preview}" if config
                           else "No Radarr credentials in .env — skipping injection",
            })

        if not config:
            return wgt_path  # nothing configured in .env, leave as-is

        config_js = (
            "(function(){{"
            "var k={key};try{{if(!localStorage.getItem(k)){{"
            "localStorage.setItem(k,JSON.stringify({val}));}}"
            "}}catch(e){{}}}})()"
        ).format(key=_json.dumps(storage_key), val=_json.dumps(config))

        tmp_dir = Path(tempfile.mkdtemp(prefix="sawsube_inject_"))
        out_wgt = Path(wgt_path).parent / f"_cfg_{Path(wgt_path).name}"
        try:
            with zipfile.ZipFile(wgt_path, "r") as zin:
                zin.extractall(tmp_dir)

            cfg_file_path = tmp_dir / Path(config_file)
            cfg_file_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_file_path.write_text(config_js, encoding="utf-8")

            # Repack — config.xml must be the first entry in a Tizen WGT
            with zipfile.ZipFile(out_wgt, "w", zipfile.ZIP_DEFLATED) as zout:
                cfg_xml = tmp_dir / "config.xml"
                if cfg_xml.is_file():
                    zout.write(cfg_xml, "config.xml")
                for fp in sorted(tmp_dir.rglob("*")):
                    if fp.is_file() and fp.resolve() != cfg_xml.resolve():
                        zout.write(fp, fp.relative_to(tmp_dir).as_posix())

            log.info("Injected config for app '%s' into WGT", app_def.get("id"))
            return str(out_wgt)
        except Exception as e:
            log.warning("Config injection failed for '%s': %s", app_def.get("id"), e)
            if out_wgt.exists():
                out_wgt.unlink()
            return wgt_path
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    async def resign_wgt(
        self, tizen_path: str, wgt_path: str, profile_name: str, output_dir: str,
        tv_id: int | None = None,
    ) -> dict[str, Any]:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        if tv_id is not None:
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id,
                "step": "resigning", "progress": 50,
                "message": f"Re-signing WGT with profile '{profile_name}'…",
            })
        res = await self.run_command(
            [tizen_path, "package", "-t", "wgt", "-s", profile_name, "-o", output_dir, "--", wgt_path],
            timeout=120.0, tv_id=tv_id, step="resigning", progress=55,
        )
        if res["returncode"] != 0:
            return {"resigned_path": None, "error": res.get("stderr") or res.get("error") or "Re-sign failed"}
        # Output WGT lives in output_dir with the original name (tizen package overwrites in place when same).
        out_name = Path(wgt_path).name
        out_path = Path(output_dir) / out_name
        if not out_path.is_file():
            # find first .wgt in dir
            for p in Path(output_dir).glob("*.wgt"):
                out_path = p
                break
        return {"resigned_path": str(out_path), "error": None}

    async def install_wgt(
        self, sdb_path: str, tizen_path: str, tv_ip: str, wgt_path: str, tv_id: int,
    ) -> dict[str, Any]:
        await ws_manager.broadcast({
            "type": "tizenbrew_install_progress", "tv_id": tv_id,
            "step": "connecting", "progress": 60,
            "message": f"Connecting to {tv_ip} via sdb…",
        })
        sc = await self.sdb_connect(tv_ip, sdb_path)
        if not sc["connected"]:
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id,
                "step": "error", "progress": 0,
                "message": f"sdb connect failed: {sc.get('output') or sc.get('error')}",
            })
            return {"success": False, "output": sc.get("output", ""),
                    "error": sc.get("error") or "sdb connect failed"}

        # Discover the exact serial registered in the sdb server so tizen install -t gets it right.
        # sdb connect <ip> registers the device as <ip>:26101, but let's verify.
        await ws_manager.broadcast({
            "type": "tizenbrew_install_progress", "tv_id": tv_id,
            "step": "connecting", "progress": 65,
            "message": "Verifying sdb device list…",
        })
        devices = await self.sdb_devices(sdb_path)
        log.info("sdb devices after connect: %s", devices)

        await ws_manager.broadcast({
            "type": "tizenbrew_install_progress", "tv_id": tv_id,
            "step": "installing", "progress": 70,
            "message": f"Installing WGT on TV ({tv_ip})…",
        })

        # Run sdb connect and tizen install as a single shell command so they share
        # the same environment/daemon session.  The -t flag is broken on this Tizen Studio
        # version ("There is no target" even when sdb shows device connected), so we omit it
        # and let tizen pick the only connected device automatically.
        shell_cmd = (
            f"{sdb_path} connect {tv_ip} && "
            f"{tizen_path} install -n {wgt_path}"
        )
        log.info("tizenbrew: running shell install: %s", shell_cmd)
        await ws_manager.broadcast({
            "type": "tizenbrew_install_progress", "tv_id": tv_id,
            "step": "installing", "progress": 75,
            "message": "Transferring and installing package…",
        })

        proc = await asyncio.create_subprocess_shell(
            shell_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out_lines: list[str] = []

        async def _read_shell() -> None:
            assert proc.stdout
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                if not text:
                    continue
                out_lines.append(text)
                log.info("tizenbrew install: %s", text)
                await ws_manager.broadcast({
                    "type": "tizenbrew_install_progress",
                    "tv_id": tv_id, "step": "installing",
                    "message": text, "progress": 85,
                })

        try:
            await asyncio.wait_for(asyncio.gather(_read_shell(), proc.wait()), timeout=300.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return {"success": False, "output": "\n".join(out_lines), "error": "Install timed out after 300s"}

        stdout = "\n".join(out_lines)
        res = {"returncode": proc.returncode or 0, "stdout": stdout, "stderr": ""}

        success = res["returncode"] == 0 and "fail" not in res["stdout"].lower() and \
                  "there is no" not in res["stdout"].lower()
        if success:
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id,
                "step": "done", "progress": 100,
                "message": "Install complete!",
            })
        else:
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id,
                "step": "error", "progress": 0,
                "message": f"Install failed: {res.get('stderr') or res['stdout'][-500:]}",
            })
        return {"success": success, "output": res["stdout"], "error": None if success else "Install failed"}

    # ── Full install pipeline ──────────────────────────────────────────────
    async def install_tizenbrew_pipeline(self, tv_id: int) -> None:
        try:
            tools = await self.find_tizen_tools()
            if not tools["found"]:
                await ws_manager.broadcast({
                    "type": "tizenbrew_install_progress", "tv_id": tv_id,
                    "step": "error", "progress": 0,
                    "message": "Tizen Studio CLI tools not found. Install Tizen Studio first.",
                })
                await self.update_state(tv_id, notes="Tizen Studio not found")
                return

            async with SessionLocal() as s:
                tv = await s.get(TV, tv_id)
            if not tv:
                await ws_manager.broadcast({
                    "type": "tizenbrew_install_progress", "tv_id": tv_id,
                    "step": "error", "progress": 0, "message": "TV not found in DB",
                })
                return

            info = await self.fetch_tv_api_info(tv.ip)
            need_cert = info.get("requires_certificate", False)

            dl = await self.download_tizenbrew_wgt(tv_id=tv_id)
            if dl["error"]:
                await self.update_state(tv_id, notes=f"Download failed: {dl['error']}")
                return
            wgt_path = dl["path"]

            profile_name: str | None = None
            if need_cert:
                state = await self.get_or_create_state(tv_id)
                profile_name = state.certificate_profile
                if not profile_name:
                    profiles = await self.list_certificate_profiles(tools["tizen_path"])
                    if profiles:
                        profile_name = profiles[0]
                if profile_name:
                    rs = await self.resign_wgt(
                        tools["tizen_path"], wgt_path, profile_name,
                        str(self.download_dir / "signed"), tv_id=tv_id,
                    )
                    if rs["error"]:
                        await self.update_state(tv_id, notes=f"Resign failed: {rs['error']}")
                        return
                    wgt_path = rs["resigned_path"] or wgt_path
                else:
                    await ws_manager.broadcast({
                        "type": "tizenbrew_install_progress", "tv_id": tv_id,
                        "step": "error", "progress": 0,
                        "message": "Tizen 7+ TV requires a Samsung certificate. Create one in Step 4 first.",
                    })
                    await self.update_state(tv_id, notes="Missing Samsung certificate")
                    return

            res = await self.install_wgt(tools["sdb_path"], tools["tizen_path"], tv.ip, wgt_path, tv_id)
            if res["success"]:
                await self.update_state(
                    tv_id,
                    tizenbrew_installed=True,
                    tizenbrew_version=dl.get("version"),
                    sdb_connected=True,
                    notes=None,
                )
            else:
                await self.update_state(tv_id, notes=res.get("error") or "install failed")
        except Exception as e:
            log.exception("install pipeline crashed")
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id,
                "step": "error", "progress": 0, "message": f"Pipeline error: {e}",
            })
            await self.update_state(tv_id, notes=str(e))

    # ── App install ────────────────────────────────────────────────────────
    async def fetch_github_wgt(self, repo: str, tv_id: int | None = None) -> dict[str, Any]:
        """Fetch latest .wgt for a repo.

        Strategy:
          1. Try GitHub Releases (`/releases/latest`) for a .wgt/.tpk asset.
          2. Fallback: HEAD/GET `https://raw.githubusercontent.com/{repo}/<branch>/<repoName>.wgt`
             where <repoName> is the second path segment, trying main → master.
             This lets repos commit a .wgt directly without cutting releases.
        """
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                # ── 1. Try releases ─────────────────────────────────────────
                try:
                    r = await client.get(api_url, headers={"Accept": "application/vnd.github+json"})
                    if r.status_code == 200:
                        rel = r.json()
                        asset = next(
                            (a for a in rel.get("assets", [])
                             if a.get("name", "").lower().endswith((".wgt", ".tpk"))),
                            None,
                        )
                        if asset:
                            target = self.download_dir / "apps" / asset["name"]
                            target.parent.mkdir(parents=True, exist_ok=True)
                            async with client.stream("GET", asset["browser_download_url"]) as resp:
                                resp.raise_for_status()
                                with open(target, "wb") as f:
                                    async for chunk in resp.aiter_bytes(64 * 1024):
                                        f.write(chunk)
                            return {"path": str(target), "version": rel.get("tag_name"), "error": None}
                except Exception as e:
                    log.warning("releases lookup failed for %s: %s — trying raw fallback", repo, e)

                # ── 2. Raw repo fallback ────────────────────────────────────
                repo_name = repo.split("/", 1)[1] if "/" in repo else repo
                # Try common .wgt names; capitalised first as that's the convention.
                wgt_candidates = [f"{repo_name}.wgt",
                                  f"{repo_name.capitalize()}.wgt",
                                  f"{repo_name.lower()}.wgt"]
                # De-dup preserving order
                seen = set()
                wgt_candidates = [w for w in wgt_candidates if not (w in seen or seen.add(w))]
                for branch in ("main", "master"):
                    for wgt_name in wgt_candidates:
                        raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{wgt_name}"
                        try:
                            head = await client.head(raw_url, follow_redirects=True)
                            if head.status_code != 200:
                                continue
                            target = self.download_dir / "apps" / wgt_name
                            target.parent.mkdir(parents=True, exist_ok=True)
                            async with client.stream("GET", raw_url) as resp:
                                resp.raise_for_status()
                                with open(target, "wb") as f:
                                    async for chunk in resp.aiter_bytes(64 * 1024):
                                        f.write(chunk)
                            log.info("Fetched %s from raw repo (%s/%s)", wgt_name, repo, branch)
                            return {"path": str(target), "version": f"raw-{branch}", "error": None}
                        except Exception:
                            continue

                return {"path": None, "version": None,
                        "error": f"No .wgt found in releases or raw repo for {repo}"}
        except Exception as e:
            return {"path": None, "version": None, "error": str(e)}

    async def fetch_url_wgt(self, url: str) -> dict[str, Any]:
        try:
            name = url.rstrip("/").split("/")[-1] or f"app-{uuid.uuid4().hex}.wgt"
            target = self.download_dir / "apps" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with open(target, "wb") as f:
                        async for chunk in resp.aiter_bytes(64 * 1024):
                            f.write(chunk)
            return {"path": str(target), "version": None, "error": None}
        except Exception as e:
            return {"path": None, "version": None, "error": str(e)}

    async def install_app_pipeline(self, tv_id: int, app_def: dict[str, Any]) -> None:
        try:
            tools = await self.find_tizen_tools()
            if not tools["found"]:
                await ws_manager.broadcast({
                    "type": "tizenbrew_install_progress", "tv_id": tv_id,
                    "step": "error", "progress": 0,
                    "message": "Tizen Studio not found",
                })
                return

            async with SessionLocal() as s:
                tv = await s.get(TV, tv_id)
            if not tv:
                return

            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id,
                "step": "downloading", "progress": 10,
                "message": f"Fetching {app_def['name']}…",
            })

            if app_def["source_type"] == "local_build":
                # Route to the dedicated local build+install pipeline which uses the
                # locally-built WGT from RADARRZEN_SRC_PATH / SONARRZEN_SRC_PATH etc.
                # This ensures the installed version matches what was built locally,
                # NOT whatever old .wgt might be committed to a remote GitHub repo.
                src = app_def.get("source", "")
                if src == "local:radarrzen" or app_def.get("id") == "radarr":
                    await self.build_and_install_radarrzen(tv_id)
                elif src == "local:sonarrzen" or app_def.get("id") == "sonarr":
                    await self.build_and_install_sonarrzen(tv_id)
                elif src == "local:fieshzen" or app_def.get("id") == "fieshzen":
                    await self.build_and_install_fieshzen(tv_id)
                elif src == "local:castafiorezen" or app_def.get("id") == "castafiorezen":
                    await self.build_and_install_castafiorezen(tv_id)
                else:
                    await ws_manager.broadcast({
                        "type": "tizenbrew_install_progress", "tv_id": tv_id,
                        "step": "error", "progress": 0,
                        "message": f"No local build pipeline configured for source '{src}'.",
                    })
                return  # dedicated pipeline handles its own completion broadcasts
            elif app_def["source_type"] == "github":
                fetched = await self.fetch_github_wgt(app_def["source"], tv_id=tv_id)
            elif app_def["source_type"] in ("wgt_url", "url"):
                fetched = await self.fetch_url_wgt(app_def["source"])
            else:
                await ws_manager.broadcast({
                    "type": "tizenbrew_install_progress", "tv_id": tv_id,
                    "step": "error", "progress": 0,
                    "message": f"Unsupported source_type: {app_def['source_type']}",
                })
                return

            if fetched["error"]:
                await ws_manager.broadcast({
                    "type": "tizenbrew_install_progress", "tv_id": tv_id,
                    "step": "error", "progress": 0,
                    "message": f"Fetch failed: {fetched['error']}",
                })
                return

            wgt_path = fetched["path"]
            # Enrich app_def with inject_config from CURATED_APPS if not already present
            if not app_def.get("inject_config"):
                for curated in CURATED_APPS:
                    if curated.get("id") == app_def.get("id"):
                        app_def = {**app_def, **{k: v for k, v in curated.items() if k not in app_def or not app_def[k]}}
                        break
            wgt_path = await self.inject_app_config(app_def, wgt_path, tv_id=tv_id)
            info = await self.fetch_tv_api_info(tv.ip)
            need_cert = info.get("requires_certificate", False)
            if need_cert and wgt_path.lower().endswith(".wgt"):
                state = await self.get_or_create_state(tv_id)
                if state.certificate_profile:
                    rs = await self.resign_wgt(
                        tools["tizen_path"], wgt_path, state.certificate_profile,
                        str(self.download_dir / "apps" / "signed"), tv_id=tv_id,
                    )
                    if rs["resigned_path"]:
                        wgt_path = rs["resigned_path"]

            res = await self.install_wgt(tools["sdb_path"], tools["tizen_path"], tv.ip, wgt_path, tv_id)
            if res["success"]:
                async with SessionLocal() as s:
                    s.add(TizenBrewInstalledApp(
                        tv_id=tv_id,
                        app_name=app_def["name"],
                        app_source=f"{app_def['source_type']}:{app_def['source']}",
                        wgt_path=wgt_path,
                        version=fetched.get("version"),
                    ))
                    await s.commit()
        except Exception as e:
            log.exception("app install crashed")
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id,
                "step": "error", "progress": 0, "message": str(e),
            })

    # ── Radarrzen local build + install ────────────────────────────────────
    async def build_and_install_radarrzen(self, tv_id: int) -> None:
        """Build Radarrzen WGT from local source, inject config BEFORE signing, install."""
        import json as _json
        import tempfile

        async def _broadcast(msg: str, pct: int, step: str = "building") -> None:
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress",
                "tv_id": tv_id, "step": step, "progress": pct, "message": msg,
            })

        tmp_src: Path | None = None
        try:
            src_path = getattr(settings, "RADARRZEN_SRC_PATH", "") or ""
            profile_name = getattr(settings, "RADARRZEN_TIZEN_PROFILE", "SAWSUBE") or "SAWSUBE"

            if not src_path or not Path(src_path).is_dir():
                await _broadcast(
                    f"RADARRZEN_SRC_PATH not set or not found ('{src_path}'). "
                    "Set it in .env to point at the radarrzen/src directory.",
                    0, "error",
                )
                return

            tools = await self.find_tizen_tools()
            if not tools["tizen_path"]:
                await _broadcast("Tizen Studio CLI not found. Install Tizen Studio or set TIZEN_CLI_PATH.", 0, "error")
                return
            if not tools["sdb_path"]:
                await _broadcast("sdb not found. Install Tizen Studio or set TIZEN_SDB_PATH.", 0, "error")
                return

            async with SessionLocal() as s:
                tv = await s.get(TV, tv_id)
            if not tv:
                await _broadcast("TV not found in DB.", 0, "error")
                return

            # Step 1: Copy source to a temp dir and inject config BEFORE signing.
            # This avoids the sign→modify→resign cycle that causes certificate errors.
            await _broadcast("Injecting Radarr config into source…", 8, "injecting")
            tmp_src = Path(tempfile.mkdtemp(prefix="sawsube_rz_"))
            shutil.copytree(src_path, str(tmp_src), dirs_exist_ok=True)

            # Remove any existing signature files so tizen package generates clean ones
            for sig_file in ("author-signature.xml", "signature1.xml", ".manifest.tmp"):
                (tmp_src / sig_file).unlink(missing_ok=True)

            cfg_js_path = tmp_src / "js" / "sawsube-config.js"
            original = cfg_js_path.read_text(encoding="utf-8") if cfg_js_path.is_file() else \
                "var TMDB_API_KEY = '__TMDB_API_KEY__';\n(function(){})();\n"

            # Inject TMDB API key
            tmdb_key = getattr(settings, "TMDB_API_KEY", "") or ""
            if tmdb_key:
                original = original.replace("'__TMDB_API_KEY__'", _json.dumps(tmdb_key))
                original = original.replace('"__TMDB_API_KEY__"', _json.dumps(tmdb_key))

            # Inject Radarr credentials as a localStorage pre-seed
            radarr_app_def = next((a for a in CURATED_APPS if a.get("id") == "radarr"), None)
            if radarr_app_def:
                inject_cfg = radarr_app_def.get("inject_config", {})
                radarr_config = {}
                for js_key, settings_attr in inject_cfg.get("fields", {}).items():
                    val = getattr(settings, settings_attr, "") or ""
                    if val:
                        radarr_config[js_key] = val
                if radarr_config:
                    storage_key = inject_cfg["storage_key"]
                    seed_js = (
                        f"(function(){{var k={_json.dumps(storage_key)};"
                        f"try{{if(!localStorage.getItem(k))"
                        f"{{localStorage.setItem(k,JSON.stringify({_json.dumps(radarr_config)}));}}"
                        f"}}catch(e){{}}}})();"
                    )
                    original = original.replace("(function(){})();", seed_js)
                    preview = {k: (v[:8] + "…" if k == "apiKey" and len(v) > 8 else v)
                               for k, v in radarr_config.items()}
                    await _broadcast(f"Injecting config into WGT: {preview}", 12, "injecting")

            cfg_js_path.write_text(original, encoding="utf-8")

            # Step 2: Package WGT from the prepared temp source (signs in one step)
            await _broadcast(f"Packaging WGT from {src_path} (profile: {profile_name})…", 15)
            out_dir_path = (self.download_dir / "radarrzen_build").resolve()
            out_dir = str(out_dir_path)
            if out_dir_path.exists():
                for old in out_dir_path.glob("*.wgt"):
                    old.unlink(missing_ok=True)
            out_dir_path.mkdir(parents=True, exist_ok=True)

            log.info("radarrzen_build: running tizen package (profile=%s, out=%s, tmp_src=%s)", profile_name, out_dir, tmp_src)
            pkg_res = await self.run_command(
                [tools["tizen_path"], "package",
                 "--type", "wgt",
                 "--sign", profile_name,
                 "-o", out_dir,
                 "--", str(tmp_src)],
                timeout=120.0, tv_id=tv_id, step="building", progress=20,
            )
            log.info("radarrzen_build: tizen package returncode=%s stdout=%r",
                     pkg_res["returncode"], pkg_res.get("stdout", "")[-300:])
            if pkg_res["returncode"] != 0:
                await _broadcast(
                    f"Build failed (exit {pkg_res['returncode']}): "
                    f"{pkg_res.get('stderr') or pkg_res['stdout'][-400:]}",
                    0, "error",
                )
                return

            # Find the produced WGT — parse stdout for authoritative location
            wgt_files = list(out_dir_path.glob("*.wgt"))
            if not wgt_files:
                for line in pkg_res.get("stdout", "").splitlines():
                    if "Package File Location:" in line:
                        located = line.split("Package File Location:")[-1].strip()
                        if Path(located).exists():
                            target = out_dir_path / Path(located).name
                            shutil.move(located, target)
                            wgt_files = [target]
                            break
            if not wgt_files:
                log.error("radarrzen_build: no .wgt produced in %s", out_dir)
                await _broadcast("Build produced no .wgt file — check your Tizen profile and src path.", 0, "error")
                return

            wgt_path = str(wgt_files[0])
            await _broadcast(f"Built: {Path(wgt_path).name}", 40)

            # Step 3: Install (no resign needed — signed correctly in step 2)
            res = await self.install_wgt(tools["sdb_path"], tools["tizen_path"], tv.ip, wgt_path, tv_id)
            if res["success"]:
                await self.update_state(tv_id, sdb_connected=True, notes=None)
                async with SessionLocal() as s:
                    s.add(TizenBrewInstalledApp(
                        tv_id=tv_id,
                        app_name="Radarrzen",
                        app_source="local:radarrzen/src",
                        wgt_path=wgt_path,
                        version="local-build",
                    ))
                    await s.commit()
            else:
                await self.update_state(tv_id, notes=res.get("error") or "install failed")

        except Exception as e:
            log.exception("build_and_install_radarrzen crashed")
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id,
                "step": "error", "progress": 0, "message": f"Build error: {e}",
            })
        finally:
            if tmp_src and tmp_src.exists():
                shutil.rmtree(tmp_src, ignore_errors=True)

    # ── Sonarrzen local build + install ────────────────────────────────────
    async def build_and_install_sonarrzen(self, tv_id: int) -> None:
        """Build Sonarrzen WGT from local source, inject config BEFORE signing, install."""
        import json as _json
        import tempfile

        async def _broadcast(msg: str, pct: int, step: str = "building") -> None:
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress",
                "tv_id": tv_id, "step": step, "progress": pct, "message": msg,
            })

        tmp_src: Path | None = None
        try:
            src_path = getattr(settings, "SONARRZEN_SRC_PATH", "") or ""
            profile_name = getattr(settings, "SONARRZEN_TIZEN_PROFILE", "SAWSUBE") or "SAWSUBE"

            if not src_path or not Path(src_path).is_dir():
                await _broadcast(
                    f"SONARRZEN_SRC_PATH not set or not found ('{src_path}'). "
                    "Set it in .env to point at the sonarrzen/src directory.",
                    0, "error",
                )
                return

            tools = await self.find_tizen_tools()
            if not tools["tizen_path"]:
                await _broadcast("Tizen Studio CLI not found. Install Tizen Studio or set TIZEN_CLI_PATH.", 0, "error")
                return
            if not tools["sdb_path"]:
                await _broadcast("sdb not found. Install Tizen Studio or set TIZEN_SDB_PATH.", 0, "error")
                return

            async with SessionLocal() as s:
                tv = await s.get(TV, tv_id)
            if not tv:
                await _broadcast("TV not found in DB.", 0, "error")
                return

            # Step 1: Copy source to temp dir and inject config BEFORE signing
            await _broadcast("Injecting Sonarr config into source…", 8, "injecting")
            tmp_src = Path(tempfile.mkdtemp(prefix="sawsube_sz_"))
            shutil.copytree(src_path, str(tmp_src), dirs_exist_ok=True)

            # Remove any existing signature files so tizen package generates clean ones
            for sig_file in ("author-signature.xml", "signature1.xml", ".manifest.tmp"):
                (tmp_src / sig_file).unlink(missing_ok=True)

            cfg_js_path = tmp_src / "js" / "sawsube-config.js"
            original = cfg_js_path.read_text(encoding="utf-8") if cfg_js_path.is_file() else \
                "var TMDB_API_KEY = '__TMDB_API_KEY__';\n(function(){})();\n"

            tmdb_key = getattr(settings, "TMDB_API_KEY", "") or ""
            if tmdb_key:
                original = original.replace("'__TMDB_API_KEY__'", _json.dumps(tmdb_key))
                original = original.replace('"__TMDB_API_KEY__"', _json.dumps(tmdb_key))

            sonarr_app_def = next((a for a in CURATED_APPS if a.get("id") == "sonarr"), None)
            if sonarr_app_def:
                inject_cfg = sonarr_app_def.get("inject_config", {})
                sonarr_config = {}
                for js_key, settings_attr in inject_cfg.get("fields", {}).items():
                    val = getattr(settings, settings_attr, "") or ""
                    if val:
                        sonarr_config[js_key] = val
                if sonarr_config:
                    storage_key = inject_cfg["storage_key"]
                    seed_js = (
                        f"(function(){{var k={_json.dumps(storage_key)};"
                        f"try{{if(!localStorage.getItem(k))"
                        f"{{localStorage.setItem(k,JSON.stringify({_json.dumps(sonarr_config)}));}}"
                        f"}}catch(e){{}}}})();"
                    )
                    original = original.replace("(function(){})();", seed_js)
                    preview = {k: (v[:8] + "…" if k == "apiKey" and len(v) > 8 else v)
                               for k, v in sonarr_config.items()}
                    await _broadcast(f"Injecting config into WGT: {preview}", 12, "injecting")

            cfg_js_path.write_text(original, encoding="utf-8")

            # Step 2: Package WGT from the prepared temp source (signs in one step)
            await _broadcast(f"Packaging WGT from {src_path} (profile: {profile_name})…", 15)
            out_dir_path = (self.download_dir / "sonarrzen_build").resolve()
            out_dir = str(out_dir_path)
            if out_dir_path.exists():
                for old in out_dir_path.glob("*.wgt"):
                    old.unlink(missing_ok=True)
            out_dir_path.mkdir(parents=True, exist_ok=True)

            log.info("sonarrzen_build: running tizen package (profile=%s, out=%s, tmp_src=%s)", profile_name, out_dir, tmp_src)
            pkg_res = await self.run_command(
                [tools["tizen_path"], "package",
                 "--type", "wgt",
                 "--sign", profile_name,
                 "-o", out_dir,
                 "--", str(tmp_src)],
                timeout=120.0, tv_id=tv_id, step="building", progress=20,
            )
            log.info("sonarrzen_build: tizen package returncode=%s stdout=%r",
                     pkg_res["returncode"], pkg_res.get("stdout", "")[-300:])
            if pkg_res["returncode"] != 0:
                await _broadcast(
                    f"Build failed (exit {pkg_res['returncode']}): "
                    f"{pkg_res.get('stderr') or pkg_res['stdout'][-400:]}",
                    0, "error",
                )
                return

            wgt_files = list(out_dir_path.glob("*.wgt"))
            if not wgt_files:
                for line in pkg_res.get("stdout", "").splitlines():
                    if "Package File Location:" in line:
                        located = line.split("Package File Location:")[-1].strip()
                        if Path(located).exists():
                            target = out_dir_path / Path(located).name
                            shutil.move(located, target)
                            wgt_files = [target]
                            break
            if not wgt_files:
                log.error("sonarrzen_build: no .wgt produced in %s", out_dir)
                await _broadcast("Build produced no .wgt file — check your Tizen profile and src path.", 0, "error")
                return

            wgt_path = str(wgt_files[0])
            await _broadcast(f"Built: {Path(wgt_path).name}", 40)

            # Step 3: Install directly (no resign needed — signed correctly in step 2)
            res = await self.install_wgt(tools["sdb_path"], tools["tizen_path"], tv.ip, wgt_path, tv_id)
            if res["success"]:
                await self.update_state(tv_id, sdb_connected=True, notes=None)
                async with SessionLocal() as s:
                    s.add(TizenBrewInstalledApp(
                        tv_id=tv_id,
                        app_name="Sonarrzen",
                        app_source="local:sonarrzen/src",
                        wgt_path=wgt_path,
                        version="local-build",
                    ))
                    await s.commit()
            else:
                await self.update_state(tv_id, notes=res.get("error") or "install failed")

        except Exception as e:
            log.exception("build_and_install_sonarrzen crashed")
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id,
                "step": "error", "progress": 0, "message": f"Build error: {e}",
            })
        finally:
            if tmp_src and tmp_src.exists():
                shutil.rmtree(tmp_src, ignore_errors=True)

    # ── Fieshzen local build + install ────────────────────────────────────────
    async def build_and_install_fieshzen(self, tv_id: int) -> None:
        """Build Fieshzen WGT from Feishin web source, inject Navidrome auth,
        sign, and install onto the TV."""
        import tempfile

        async def _broadcast(msg: str, pct: int, step: str = "building") -> None:
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress",
                "tv_id": tv_id, "step": step, "progress": pct, "message": msg,
            })

        try:
            feishin_src = getattr(settings, "FIESHZEN_FEISHIN_SRC_PATH", "") or ""
            fieshzen_src = getattr(settings, "FIESHZEN_SRC_PATH", "") or ""
            profile_name = getattr(settings, "FIESHZEN_TIZEN_PROFILE", "SAWSUBE") or "SAWSUBE"
            nd_url = getattr(settings, "NAVIDROME_URL", "") or ""
            nd_user = getattr(settings, "NAVIDROME_USERNAME", "") or ""
            nd_pass = getattr(settings, "NAVIDROME_PASSWORD", "") or ""
            nd_name = getattr(settings, "NAVIDROME_SERVER_NAME", "") or nd_user

            if not feishin_src or not Path(feishin_src).is_dir():
                await _broadcast(
                    f"FIESHZEN_FEISHIN_SRC_PATH not set or not found ('{feishin_src}'). "
                    "Set it in .env to point at the feishin source directory.",
                    0, "error",
                )
                return
            if not fieshzen_src or not Path(fieshzen_src).is_dir():
                await _broadcast(
                    f"FIESHZEN_SRC_PATH not set or not found ('{fieshzen_src}'). "
                    "Set it in .env to point at the Fieshzen repo directory.",
                    0, "error",
                )
                return

            tools = await self.find_tizen_tools()
            if not tools["tizen_path"]:
                await _broadcast("Tizen Studio CLI not found.", 0, "error")
                return
            if not tools["sdb_path"]:
                await _broadcast("sdb not found.", 0, "error")
                return

            async with SessionLocal() as s:
                tv = await s.get(TV, tv_id)
            if not tv:
                await _broadcast("TV not found in DB.", 0, "error")
                return

            # ── Step 1: authenticate with Navidrome ───────────────────────
            await _broadcast("Authenticating with Navidrome…", 5)
            nd_auth: dict[str, Any] = {}
            if nd_url and nd_user and nd_pass:
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        r = await client.post(
                            f"{nd_url.rstrip('/')}/auth/login",
                            json={"username": nd_user, "password": nd_pass},
                            headers={"Content-Type": "application/json"},
                        )
                        if r.status_code == 200:
                            nd_auth = r.json()
                            await _broadcast(
                                f"Navidrome auth OK (user: {nd_auth.get('username', nd_user)})",
                                8,
                            )
                        else:
                            await _broadcast(
                                f"Navidrome auth failed (HTTP {r.status_code}) — "
                                "building without pre-seeded credentials",
                                8,
                            )
                except Exception as e:
                    await _broadcast(f"Navidrome unreachable: {e} — building without auth", 8)
            else:
                await _broadcast(
                    "NAVIDROME_URL/USERNAME/PASSWORD not set — skipping auth pre-seed", 8,
                )

            # ── Step 2: pnpm install ───────────────────────────────────────
            pnpm_path = shutil.which("pnpm")
            if not pnpm_path:
                await _broadcast(
                    "pnpm not found on PATH. Install pnpm: npm install -g pnpm", 0, "error",
                )
                return

            await _broadcast("Running pnpm install in feishin source…", 10)
            install_res = await self.run_command(
                [pnpm_path, "install", "--frozen-lockfile"],
                timeout=600.0,
                cwd=feishin_src,
                tv_id=tv_id, step="building", progress=12,
            )
            if install_res["returncode"] != 0:
                await _broadcast(
                    f"pnpm install failed: {install_res.get('stderr') or install_res['stdout'][-400:]}",
                    0, "error",
                )
                return

            # ── Step 3: pnpm build:web ────────────────────────────────────
            await _broadcast("Building Feishin web app (pnpm build:web)…", 20)
            build_res = await self.run_command(
                [pnpm_path, "build:web"],
                timeout=900.0,
                cwd=feishin_src,
                tv_id=tv_id, step="building", progress=25,
            )
            if build_res["returncode"] != 0:
                await _broadcast(
                    f"pnpm build:web failed: {build_res.get('stderr') or build_res['stdout'][-400:]}",
                    0, "error",
                )
                return

            web_out = Path(feishin_src) / "out" / "web"
            if not web_out.is_dir() or not (web_out / "index.html").is_file():
                await _broadcast(
                    "Build produced no out/web/index.html — check feishin build output.",
                    0, "error",
                )
                return
            await _broadcast(f"Web build complete: {web_out}", 45)

            # ── Step 4: assemble WGT directory ─────────────────────────────
            await _broadcast("Assembling WGT directory…", 48)
            tmp_dir = Path(tempfile.mkdtemp(prefix="fieshzen_wgt_"))
            try:
                shutil.copytree(str(web_out), str(tmp_dir), dirs_exist_ok=True)

                config_xml_src = Path(fieshzen_src) / "tizen" / "config.xml"
                if not config_xml_src.is_file():
                    await _broadcast(f"config.xml not found at {config_xml_src}", 0, "error")
                    return
                shutil.copy(config_xml_src, tmp_dir / "config.xml")

                patches_dir = Path(fieshzen_src) / "patches"
                for patch_file in ("tizen-compat.js", "tizen-fixes.css"):
                    src = patches_dir / patch_file
                    if src.is_file():
                        shutil.copy(src, tmp_dir / patch_file)
                    else:
                        await _broadcast(f"Warning: patch file not found: {src}", 48)

                # ── Step 5: write settings.js ───────────────────────────────
                await _broadcast("Writing settings.js…", 50)
                settings_js = self._generate_fieshzen_settings_js(
                    server_url=nd_url or "",
                    server_name=nd_name or nd_user or "",
                    username=nd_user or "",
                    password=nd_pass or "",
                )
                (tmp_dir / "settings.js").write_text(settings_js, encoding="utf-8")

                # ── Step 6: write fieshzen-auth.js (if auth succeeded) ─────
                if nd_auth:
                    await _broadcast("Writing fieshzen-auth.js…", 52)
                    auth_js = self._generate_fieshzen_auth_js(
                        server_url=nd_url,
                        server_name=nd_name,
                        auth=nd_auth,
                    )
                    (tmp_dir / "fieshzen-auth.js").write_text(auth_js, encoding="utf-8")

                    await _broadcast("Patching index.html with auth + compat scripts…", 54)
                    index_html_path = tmp_dir / "index.html"
                    index_html = index_html_path.read_text(encoding="utf-8")
                    inject_block = (
                        '<script src="fieshzen-auth.js"></script>\n'
                        '    <script src="settings.js"></script>\n'
                        '    <link rel="stylesheet" href="tizen-fixes.css">\n'
                        '    <script src="tizen-compat.js"></script>'
                    )
                    if '<script src="settings.js"></script>' in index_html:
                        index_html = index_html.replace(
                            '<script src="settings.js"></script>',
                            inject_block,
                            1,
                        )
                    else:
                        index_html = index_html.replace(
                            '</head>',
                            f'    {inject_block}\n  </head>',
                            1,
                        )
                    index_html_path.write_text(index_html, encoding="utf-8")
                else:
                    # no auth — still inject compat scripts
                    index_html_path = tmp_dir / "index.html"
                    index_html = index_html_path.read_text(encoding="utf-8")
                    inject_block = (
                        '<script src="settings.js"></script>\n'
                        '    <link rel="stylesheet" href="tizen-fixes.css">\n'
                        '    <script src="tizen-compat.js"></script>'
                    )
                    if '<script src="settings.js"></script>' in index_html:
                        index_html = index_html.replace(
                            '<script src="settings.js"></script>',
                            inject_block,
                            1,
                        )
                    else:
                        index_html = index_html.replace(
                            '</head>',
                            f'    {inject_block}\n  </head>',
                            1,
                        )
                    index_html_path.write_text(index_html, encoding="utf-8")

                # ── Step 7: package WGT ────────────────────────────────────
                await _broadcast(f"Packaging WGT (profile: {profile_name})…", 58)
                out_dir_path = self.download_dir / "fieshzen_build"
                out_dir_path.mkdir(parents=True, exist_ok=True)
                for old in out_dir_path.glob("*.wgt"):
                    old.unlink(missing_ok=True)

                pkg_res = await self.run_command(
                    [tools["tizen_path"], "package",
                     "--type", "wgt",
                     "--sign", profile_name,
                     "-o", str(out_dir_path),
                     "--", str(tmp_dir)],
                    timeout=300.0, tv_id=tv_id, step="building", progress=65,
                )
                if pkg_res["returncode"] != 0:
                    await _broadcast(
                        f"WGT packaging failed: {pkg_res.get('stderr') or pkg_res['stdout'][-400:]}",
                        0, "error",
                    )
                    return

                wgt_files = list(out_dir_path.glob("*.wgt"))
                if not wgt_files:
                    await _broadcast("No .wgt file produced — check Tizen profile.", 0, "error")
                    return

                wgt_path = str(wgt_files[0])
                await _broadcast(f"Built: {Path(wgt_path).name}", 70)

            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

            # ── Step 8: re-sign if TV requires it ─────────────────────────
            info = await self.fetch_tv_api_info(tv.ip)
            if info.get("requires_certificate"):
                state = await self.get_or_create_state(tv_id)
                if state.certificate_profile:
                    await _broadcast("Re-signing for Tizen 7+ TV…", 72, "resigning")
                    rs = await self.resign_wgt(
                        tools["tizen_path"], wgt_path, state.certificate_profile,
                        str(self.download_dir / "fieshzen_build" / "signed"), tv_id=tv_id,
                    )
                    if rs.get("error"):
                        await _broadcast(f"Re-sign failed: {rs['error']}", 0, "error")
                        return
                    wgt_path = rs["resigned_path"] or wgt_path

            # ── Step 9: install ────────────────────────────────────────────
            res = await self.install_wgt(
                tools["sdb_path"], tools["tizen_path"], tv.ip, wgt_path, tv_id,
            )
            if res["success"]:
                await self.update_state(tv_id, sdb_connected=True, notes=None)
                async with SessionLocal() as s:
                    s.add(TizenBrewInstalledApp(
                        tv_id=tv_id,
                        app_name="Fieshzen",
                        app_source="local:fieshzen",
                        wgt_path=wgt_path,
                        version="local-build",
                    ))
                    await s.commit()
            else:
                await self.update_state(tv_id, notes=res.get("error") or "install failed")

        except Exception as e:
            log.exception("build_and_install_fieshzen crashed")
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id,
                "step": "error", "progress": 0, "message": f"Build error: {e}",
            })

    # ── Castafiorezen local build + install ──────────────────────────────────
    async def build_and_install_castafiorezen(self, tv_id: int) -> None:
        """Build Castafiorezen WGT from local src/ folder, inject Navidrome
        credentials into js/sawsube-config.js, sign, and install onto the TV."""
        import tempfile

        async def _broadcast(msg: str, pct: int, step: str = "building") -> None:
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress",
                "tv_id": tv_id, "step": step, "progress": pct, "message": msg,
            })

        try:
            cz_src = getattr(settings, "CASTAFIOREZEN_SRC_PATH", "") or ""
            profile_name = (
                getattr(settings, "CASTAFIOREZEN_TIZEN_PROFILE", "SAWSUBE") or "SAWSUBE"
            )
            nd_url = getattr(settings, "NAVIDROME_URL", "") or ""
            nd_user = getattr(settings, "NAVIDROME_USERNAME", "") or ""
            nd_pass = getattr(settings, "NAVIDROME_PASSWORD", "") or ""

            if not cz_src or not Path(cz_src).is_dir():
                await _broadcast(
                    f"CASTAFIOREZEN_SRC_PATH not set or not found ('{cz_src}'). "
                    "Set it in .env to point at the Castafiorezen repo directory.",
                    0, "error",
                )
                return
            cz_src_dir = Path(cz_src) / "src"
            if not cz_src_dir.is_dir():
                await _broadcast(
                    f"Castafiorezen src/ folder not found at {cz_src_dir}", 0, "error",
                )
                return
            if not (nd_url and nd_user and nd_pass):
                await _broadcast(
                    "NAVIDROME_URL/USERNAME/PASSWORD not set — required for Castafiorezen.",
                    0, "error",
                )
                return

            tools = await self.find_tizen_tools()
            if not tools["tizen_path"]:
                await _broadcast("Tizen Studio CLI not found.", 0, "error")
                return
            if not tools["sdb_path"]:
                await _broadcast("sdb not found.", 0, "error")
                return

            async with SessionLocal() as s:
                tv = await s.get(TV, tv_id)
            if not tv:
                await _broadcast("TV not found in DB.", 0, "error")
                return

            await _broadcast("Assembling Castafiorezen WGT directory…", 20)
            tmp_dir = Path(tempfile.mkdtemp(prefix="castafiorezen_wgt_"))
            try:
                shutil.copytree(str(cz_src_dir), str(tmp_dir), dirs_exist_ok=True)

                # Inject credentials into sawsube-config.js
                cfg = {
                    "serverUrl": nd_url,
                    "username": nd_user,
                    "password": nd_pass,
                }
                cfg_js = (
                    "(function(){var k='cz-server';try{"
                    "if(!localStorage.getItem(k)){"
                    f"localStorage.setItem(k,JSON.stringify({json.dumps(cfg)}));"
                    "}}catch(e){}})();\n"
                )
                cfg_path = tmp_dir / "js" / "sawsube-config.js"
                cfg_path.parent.mkdir(parents=True, exist_ok=True)
                cfg_path.write_text(cfg_js, encoding="utf-8")
                await _broadcast("Injected Navidrome credentials.", 35)

                await _broadcast(f"Packaging WGT (profile: {profile_name})…", 50)
                out_dir_path = self.download_dir / "castafiorezen_build"
                out_dir_path.mkdir(parents=True, exist_ok=True)
                for old in out_dir_path.glob("*.wgt"):
                    old.unlink(missing_ok=True)

                pkg_res = await self.run_command(
                    [tools["tizen_path"], "package",
                     "--type", "wgt",
                     "--sign", profile_name,
                     "-o", str(out_dir_path),
                     "--", str(tmp_dir)],
                    timeout=300.0, tv_id=tv_id, step="building", progress=60,
                )
                if pkg_res["returncode"] != 0:
                    await _broadcast(
                        f"WGT packaging failed: {pkg_res.get('stderr') or pkg_res['stdout'][-400:]}",
                        0, "error",
                    )
                    return

                wgt_files = list(out_dir_path.glob("*.wgt"))
                if not wgt_files:
                    await _broadcast("No .wgt file produced — check Tizen profile.", 0, "error")
                    return
                wgt_path = str(wgt_files[0])
                await _broadcast(f"Built: {Path(wgt_path).name}", 70)

            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

            # Re-sign if TV requires it
            info = await self.fetch_tv_api_info(tv.ip)
            if info.get("requires_certificate"):
                state = await self.get_or_create_state(tv_id)
                if state.certificate_profile:
                    await _broadcast("Re-signing for Tizen 7+ TV…", 75, "resigning")
                    rs = await self.resign_wgt(
                        tools["tizen_path"], wgt_path, state.certificate_profile,
                        str(self.download_dir / "castafiorezen_build" / "signed"), tv_id=tv_id,
                    )
                    if rs.get("error"):
                        await _broadcast(f"Re-sign failed: {rs['error']}", 0, "error")
                        return
                    wgt_path = rs["resigned_path"] or wgt_path

            res = await self.install_wgt(
                tools["sdb_path"], tools["tizen_path"], tv.ip, wgt_path, tv_id,
            )
            if res["success"]:
                await self.update_state(tv_id, sdb_connected=True, notes=None)
                async with SessionLocal() as s:
                    s.add(TizenBrewInstalledApp(
                        tv_id=tv_id,
                        app_name="Castafiorezen",
                        app_source="local:castafiorezen",
                        wgt_path=wgt_path,
                        version="local-build",
                    ))
                    await s.commit()
            else:
                await self.update_state(tv_id, notes=res.get("error") or "install failed")

        except Exception as e:
            log.exception("build_and_install_castafiorezen crashed")
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id,
                "step": "error", "progress": 0, "message": f"Build error: {e}",
            })

    def _generate_fieshzen_settings_js(
        self, server_url: str, server_name: str,
        username: str = "", password: str = "",
    ) -> str:
        """Generate the settings.js content for Feishin web build."""
        auto_login_lines = ""
        if username and password:
            auto_login_lines = (
                f"window.AUTO_LOGIN_USERNAME = {json.dumps(username)};\n"
                f"window.AUTO_LOGIN_PASSWORD = {json.dumps(password)};\n"
            )
        return f'''"use strict";

window.SERVER_URL = {json.dumps(server_url)};
window.SERVER_NAME = {json.dumps(server_name)};
window.SERVER_TYPE = "navidrome";
window.SERVER_LOCK = "true";
window.LEGACY_AUTHENTICATION = "false";
window.ANALYTICS_DISABLED = "true";
window.REMOTE_URL = "";
{auto_login_lines}
window.FS_GENERAL_THEME = "defaultDark";
window.FS_GENERAL_THEME_DARK = "defaultDark";
window.FS_GENERAL_FOLLOW_CURRENT_SONG = "true";
window.FS_GENERAL_HOME_FEATURE = "true";
window.FS_GENERAL_SHOW_LYRICS_IN_SIDEBAR = "false";
window.FS_PLAYBACK_MEDIA_SESSION = "true";
window.FS_PLAYBACK_SCROBBLE_ENABLED = "false";
window.FS_PLAYBACK_TRANSCODE_ENABLED = "false";
window.FS_LYRICS_FETCH = "true";
window.FS_LYRICS_FOLLOW = "true";
window.FS_DISCORD_ENABLED = "false";
window.FS_AUTO_DJ_ENABLED = "false";
'''

    def _generate_fieshzen_auth_js(
        self, server_url: str, server_name: str, auth: dict[str, Any],
    ) -> str:
        """Generate fieshzen-auth.js — pre-seeds Zustand auth state to bypass login."""
        user_id = auth.get("id", "")
        username = auth.get("username", "")
        is_admin = bool(auth.get("isAdmin", False))
        salt = auth.get("subsonicSalt", "")
        token = auth.get("subsonicToken", "")
        jwt = auth.get("token", "")
        credential = f"u={username}&s={salt}&t={token}&v=1.16.1&c=fieshzen"
        server_id = "fieshzen-navidrome-auto"
        server = {
            "id": server_id,
            "name": server_name or username,
            "url": server_url,
            "type": "navidrome",
            "username": username,
            "userId": user_id,
            "credential": credential,
            "ndCredential": jwt,
            "isAdmin": is_admin,
            "savePassword": True,
        }
        state = {
            "state": {
                "currentServer": server,
                "deviceId": "fieshzen-tv-device-001",
                "serverList": {server_id: server},
            },
            "version": 2,
        }
        state_json = json.dumps(state, separators=(",", ":"))
        return (
            "(function(){\n"
            '  var AUTH_KEY="store_authentication";\n'
            "  try{\n"
            f"    localStorage.setItem(AUTH_KEY,{json.dumps(state_json)});\n"
            "  }catch(e){console.error(\"Fieshzen auth pre-seed failed:\",e);}\n"
            "})();\n"
        )

    # ── Module scaffolder ──────────────────────────────────────────────────
    def generate_module_scaffold(self, data: CustomModuleCreate) -> dict[str, Any]:
        pkg_name = re.sub(r"[^a-z0-9\-]", "-", data.package_name.lower()).strip("-")
        if not pkg_name:
            pkg_name = "my-tizenbrew-module"

        if data.package_type == "app":
            pkg: dict[str, Any] = {
                "name": pkg_name,
                "version": "1.0.0",
                "description": data.description or "",
                "packageType": "app",
                "appName": data.app_name,
                "appPath": data.app_path or "app/index.html",
                "main": "app/index.html",
                "keys": data.keys,
                "evaluateScriptOnDocumentStart": data.evaluate_on_start,
            }
            if data.service_file:
                pkg["serviceFile"] = data.service_file
        else:  # mods
            pkg = {
                "name": pkg_name,
                "version": "1.0.0",
                "description": data.description or "",
                "packageType": "mods",
                "appName": data.app_name,
                "websiteURL": data.website_url or "",
                "main": "inject.js",
                "keys": data.keys,
                "evaluateScriptOnDocumentStart": data.evaluate_on_start,
            }
            if data.service_file:
                pkg["serviceFile"] = data.service_file

        readme = self._render_readme(pkg, data)
        instructions = self._render_instructions(pkg_name)

        service_file = None
        if data.service_file:
            service_file = (
                "// TizenBrew service worker — runs in Node.js context on the TV.\n"
                "// Exported functions are callable from the page via TizenBrew bridge.\n\n"
                "module.exports = {\n"
                "  onStart() {\n"
                "    console.log('[" + pkg_name + "] service started');\n"
                "  },\n"
                "  hello(name) {\n"
                "    return 'Hello, ' + name;\n"
                "  },\n"
                "};\n"
            )

        inject_file = None
        if data.package_type == "mods":
            inject_file = (
                "// TizenBrew site-modification entry point.\n"
                "// Runs inside the target website (" + (data.website_url or "?") + ").\n"
                "(function () {\n"
                "  console.log('[" + pkg_name + "] injected');\n"
                "  // Your modifications go here.\n"
                "})();\n"
            )

        return {
            "package_json": pkg,
            "readme": readme,
            "instructions": instructions,
            "service_file": service_file,
            "inject_file": inject_file,
        }

    def _render_readme(self, pkg: dict[str, Any], data: CustomModuleCreate) -> str:
        keys = ", ".join(data.keys) if data.keys else "(none)"
        body = (
            f"# {pkg['appName']}\n\n"
            f"{data.description or 'A TizenBrew module.'}\n\n"
            f"- **Package:** `{pkg['name']}`\n"
            f"- **Type:** `{pkg['packageType']}`\n"
            f"- **Remote keys:** {keys}\n"
        )
        if pkg["packageType"] == "app":
            body += f"- **Entry:** `{pkg['appPath']}`\n"
        else:
            body += f"- **Target site:** {pkg.get('websiteURL') or '(set me)'}\n"
        body += (
            "\n## Install on TizenBrew\n\n"
            "1. Open TizenBrew on your TV.\n"
            "2. Go to **Modules → Add Module**.\n"
            f"3. Enter `{pkg['name']}`.\n"
            "4. Reboot TizenBrew.\n\n"
            "## Develop\n\n"
            "Edit files, bump version in `package.json`, then `npm publish --access public`.\n"
        )
        return body

    def _render_instructions(self, pkg_name: str) -> str:
        return (
            "1. Sign up for an npm account at https://www.npmjs.com/signup\n"
            "2. In a terminal: `npm login`\n"
            f"3. From this scaffold folder: `npm publish --access public`\n"
            f"4. On your TV, open TizenBrew → Modules → Add → enter `{pkg_name}`\n"
            "5. Reboot TizenBrew. Your module appears in the list.\n"
        )


tizenbrew_service = TizenBrewService()
