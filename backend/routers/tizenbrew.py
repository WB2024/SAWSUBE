from __future__ import annotations
import asyncio
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models.tv import TV
from ..models.tizenbrew import TizenBrewState, TizenBrewInstalledApp
from ..schemas_tizenbrew import (
    TizenInfoResponse, SdbStatusResponse, ToolsStatus,
    CertificateCreate, CertificateStatus, TizenBrewStateOut,
    AppDefinition, InstalledAppOut, CustomModuleCreate, ModuleScaffoldResponse,
    JobStarted,
)
from ..services.tizenbrew_service import tizenbrew_service, CURATED_APPS

router = APIRouter(prefix="/api/tizenbrew", tags=["tizenbrew"])


# ── Tools ────────────────────────────────────────────────────────────────────
@router.get("/tools", response_model=ToolsStatus)
async def get_tools():
    return ToolsStatus(**(await tizenbrew_service.find_tizen_tools()))


# ── Curated apps catalog ─────────────────────────────────────────────────────
@router.get("/apps", response_model=list[AppDefinition])
async def list_curated_apps():
    return [AppDefinition(**a) for a in CURATED_APPS]


# ── Certificates (global) ────────────────────────────────────────────────────
@router.get("/certificates")
async def list_certificates():
    tools = await tizenbrew_service.find_tizen_tools()
    if not tools["tizen_path"]:
        raise HTTPException(400, "tizen CLI not found. Install Tizen Studio.")
    profiles = await tizenbrew_service.list_certificate_profiles(tools["tizen_path"])
    return {"profiles": profiles}


# ── Module scaffold (global) ─────────────────────────────────────────────────
@router.post("/module/scaffold", response_model=ModuleScaffoldResponse)
async def scaffold_module(payload: CustomModuleCreate):
    if not payload.package_name.strip():
        raise HTTPException(400, "package_name required")
    if not payload.app_name.strip():
        raise HTTPException(400, "app_name required")
    if payload.package_type == "mods" and not payload.website_url:
        raise HTTPException(400, "website_url required for 'mods' package type")
    return ModuleScaffoldResponse(**tizenbrew_service.generate_module_scaffold(payload))


# ── Per-TV info ──────────────────────────────────────────────────────────────
@router.get("/{tv_id}/info", response_model=TizenInfoResponse)
async def tv_info(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    info = await tizenbrew_service.fetch_tv_api_info(tv.ip)
    # Persist model/year on TV row when first discovered
    await tizenbrew_service.update_tv_model_year(tv_id, info.get("model_name"), info.get("tizen_year"))
    # Persist developer mode flag in state
    await tizenbrew_service.update_state(
        tv_id,
        developer_mode_detected=bool(info.get("developer_mode")),
        tizen_version=info.get("tizen_version"),
        tizen_year=info.get("tizen_year"),
        notes=info.get("error"),
    )
    return TizenInfoResponse(
        tv_id=tv_id,
        ip=tv.ip,
        developer_mode=bool(info.get("developer_mode")),
        developer_ip=info.get("developer_ip"),
        tizen_version=info.get("tizen_version"),
        tizen_year=info.get("tizen_year"),
        model_name=info.get("model_name"),
        requires_certificate=bool(info.get("requires_certificate")),
        error=info.get("error"),
    )


@router.get("/{tv_id}/status", response_model=TizenBrewStateOut)
async def tv_state(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    state = await tizenbrew_service.get_or_create_state(tv_id)
    return state


# ── sdb ──────────────────────────────────────────────────────────────────────
@router.post("/{tv_id}/sdb-connect", response_model=SdbStatusResponse)
async def sdb_connect(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    tools = await tizenbrew_service.find_tizen_tools()
    if not tools["sdb_path"]:
        return SdbStatusResponse(
            tv_id=tv_id, sdb_available=False, tizen_available=bool(tools["tizen_path"]),
            tv_connected=False,
            error="sdb binary not found. Install Tizen Studio.",
        )
    res = await tizenbrew_service.sdb_connect(tv.ip, tools["sdb_path"])
    devices = await tizenbrew_service.sdb_devices(tools["sdb_path"])
    connected = res["connected"] or any(tv.ip in d for d in devices)
    await tizenbrew_service.update_state(tv_id, sdb_connected=connected,
                                         notes=None if connected else res.get("output", "")[-500:])
    return SdbStatusResponse(
        tv_id=tv_id,
        sdb_available=True,
        tizen_available=bool(tools["tizen_path"]),
        tv_connected=connected,
        error=None if connected else (res.get("error") or res.get("output", "")[-300:]),
    )


@router.get("/{tv_id}/sdb-devices")
async def sdb_devices(tv_id: int):
    tools = await tizenbrew_service.find_tizen_tools()
    if not tools["sdb_path"]:
        raise HTTPException(400, "sdb binary not found")
    return {"devices": await tizenbrew_service.sdb_devices(tools["sdb_path"])}


# ── Certificate creation ─────────────────────────────────────────────────────
@router.post("/{tv_id}/certificate", response_model=JobStarted, status_code=202)
async def create_certificate(
    tv_id: int, payload: CertificateCreate, s: AsyncSession = Depends(get_session),
):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    if not payload.password:
        raise HTTPException(400, "password required")
    tools = await tizenbrew_service.find_tizen_tools()
    if not tools["tizen_path"]:
        raise HTTPException(400, "tizen CLI not found. Install Tizen Studio.")

    job_id = uuid.uuid4().hex
    asyncio.create_task(tizenbrew_service.create_samsung_certificate(
        tools["tizen_path"], payload.profile_name, payload.password,
        payload.country, payload.state, payload.city, payload.org, tv_id=tv_id,
    ))
    return JobStarted(started=True, job_id=job_id)


# ── TizenBrew install ────────────────────────────────────────────────────────
@router.post("/{tv_id}/install-tizenbrew", response_model=JobStarted, status_code=202)
async def install_tizenbrew(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    job_id = uuid.uuid4().hex
    asyncio.create_task(tizenbrew_service.install_tizenbrew_pipeline(tv_id))
    return JobStarted(started=True, job_id=job_id)


# ── App install ──────────────────────────────────────────────────────────────
@router.post("/{tv_id}/install-app", response_model=JobStarted, status_code=202)
async def install_app(
    tv_id: int, payload: AppDefinition, s: AsyncSession = Depends(get_session),
):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    job_id = uuid.uuid4().hex
    asyncio.create_task(tizenbrew_service.install_app_pipeline(tv_id, payload.model_dump()))
    return JobStarted(started=True, job_id=job_id)


@router.get("/{tv_id}/installed-apps", response_model=list[InstalledAppOut])
async def installed_apps(tv_id: int, s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(
        select(TizenBrewInstalledApp)
        .where(TizenBrewInstalledApp.tv_id == tv_id)
        .order_by(TizenBrewInstalledApp.installed_at.desc())
    )).scalars().all()
    return rows


# ── Radarrzen local build + install ──────────────────────────────────────────
@router.post("/{tv_id}/build-install-radarrzen", response_model=JobStarted, status_code=202)
async def build_install_radarrzen(tv_id: int, s: AsyncSession = Depends(get_session)):
    """Build Radarrzen WGT from local source (RADARRZEN_SRC_PATH), inject Radarr
    credentials, re-sign if required, and install onto the TV."""
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    job_id = uuid.uuid4().hex
    asyncio.create_task(tizenbrew_service.build_and_install_radarrzen(tv_id))
    return JobStarted(started=True, job_id=job_id)


# ── Sonarrzen local build + install ──────────────────────────────────────────
@router.post("/{tv_id}/build-install-sonarrzen", response_model=JobStarted, status_code=202)
async def build_install_sonarrzen(tv_id: int, s: AsyncSession = Depends(get_session)):
    """Build Sonarrzen WGT from local source (SONARRZEN_SRC_PATH), inject Sonarr
    credentials, re-sign if required, and install onto the TV."""
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    job_id = uuid.uuid4().hex
    asyncio.create_task(tizenbrew_service.build_and_install_sonarrzen(tv_id))
    return JobStarted(started=True, job_id=job_id)


# ── Fieshzen local build + install ───────────────────────────────────────────
@router.post("/{tv_id}/build-install-fieshzen", response_model=JobStarted, status_code=202)
async def build_install_fieshzen(tv_id: int, s: AsyncSession = Depends(get_session)):
    """Build Fieshzen WGT from Feishin web source, inject Navidrome credentials,
    re-sign if required, and install onto the TV."""
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    job_id = uuid.uuid4().hex
    asyncio.create_task(tizenbrew_service.build_and_install_fieshzen(tv_id))
    return JobStarted(started=True, job_id=job_id)
