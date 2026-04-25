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
        "source_type": "github",
        "source": "WB2024/radarrzen",
        "category": "Media",
        "inject_config": {
            "storage_key": "radarrzen-config",
            "config_file": "js/sawsube-config.js",
            "fields": {"url": "RADARR_URL", "apiKey": "RADARR_API_KEY"},
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

        if sdb_override and Path(sdb_override).is_file():
            sdb_path = sdb_override
        if tizen_override and Path(tizen_override).is_file():
            tizen_path = tizen_override

        if not sdb_path:
            sdb_path = shutil.which("sdb")
        if not tizen_path:
            tizen_path = shutil.which("tizen")

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
    ) -> dict[str, Any]:
        log.info("tizenbrew: running %s", " ".join(cmd))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
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
            # The p12 is placed in ~/SamsungCertificate/<alias>/ by Tizen Studio CLI.
            # Try that path; fall back to download_dir.
            home = Path.home()
            samsung_cert_dir = home / "SamsungCertificate" / profile_name
            p12_candidates = [
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

    async def inject_app_config(self, app_def: dict[str, Any], wgt_path: str) -> str:
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
            return wgt_path

        storage_key: str = inject_cfg["storage_key"]
        config_file: str = inject_cfg.get("config_file", "js/sawsube-config.js")
        fields: dict[str, str] = inject_cfg.get("fields", {})

        config: dict[str, str] = {}
        for js_key, settings_attr in fields.items():
            val = getattr(settings, settings_attr, "") or ""
            if val:
                config[js_key] = val

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

        # Find which serial matches this TV's IP
        sdb_serial: str | None = next(
            (d for d in devices if d.startswith(tv_ip)), None
        )
        if not sdb_serial:
            # Fallback: use ip:26101 (standard Tizen TV port)
            sdb_serial = f"{tv_ip}:26101"

        await ws_manager.broadcast({
            "type": "tizenbrew_install_progress", "tv_id": tv_id,
            "step": "installing", "progress": 70,
            "message": f"Installing WGT on TV (target: {sdb_serial})…",
        })

        async def _tizen_install(target_flag: list[str]) -> dict[str, Any]:
            return await self.run_command(
                [tizen_path, "install", "-n", wgt_path, *target_flag],
                timeout=240.0, tv_id=tv_id, step="installing", progress=85,
            )

        # Attempt 1: with exact sdb serial
        res = await _tizen_install(["-t", sdb_serial])
        no_target = "there is no" in res["stdout"].lower() and "target" in res["stdout"].lower()

        # Attempt 2: bare IP (some Tizen CLI versions don't include the port)
        if res["returncode"] != 0 and no_target and ":" in sdb_serial:
            bare_ip = sdb_serial.split(":")[0]
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id,
                "step": "installing", "progress": 75,
                "message": f"Retrying with bare IP target: {bare_ip}…",
            })
            res = await _tizen_install(["-t", bare_ip])
            no_target = "there is no" in res["stdout"].lower() and "target" in res["stdout"].lower()

        # Attempt 3: no -t (installs on first connected device)
        if res["returncode"] != 0 and no_target:
            await ws_manager.broadcast({
                "type": "tizenbrew_install_progress", "tv_id": tv_id,
                "step": "installing", "progress": 78,
                "message": "Retrying without explicit target (auto-detect device)…",
            })
            res = await _tizen_install([])

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
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                r = await client.get(url, headers={"Accept": "application/vnd.github+json"})
                r.raise_for_status()
                rel = r.json()
                asset = next(
                    (a for a in rel.get("assets", [])
                     if a.get("name", "").lower().endswith((".wgt", ".tpk"))),
                    None,
                )
                if not asset:
                    return {"path": None, "version": None,
                            "error": f"No .wgt/.tpk asset in latest release of {repo}"}
                target = self.download_dir / "apps" / asset["name"]
                target.parent.mkdir(parents=True, exist_ok=True)
                async with client.stream("GET", asset["browser_download_url"]) as resp:
                    resp.raise_for_status()
                    with open(target, "wb") as f:
                        async for chunk in resp.aiter_bytes(64 * 1024):
                            f.write(chunk)
                return {"path": str(target), "version": rel.get("tag_name"), "error": None}
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

            if app_def["source_type"] == "github":
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
            wgt_path = await self.inject_app_config(app_def, wgt_path)
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
