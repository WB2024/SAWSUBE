from __future__ import annotations
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_session
from ..models.folder import WatchFolder
from ..schemas import FolderCreate, FolderOut, ImportPayload, ImageOut
from ..services.watcher import watcher, scan_folder_now
from ..services.sources import unsplash, nasa_apod, rijksmuseum, reddit
from ..services.sources.common import download_and_register

router = APIRouter(prefix="/api/sources", tags=["sources"])


# ── Folders ────────────────────────────────────────────────────────────────
@router.get("/folders", response_model=list[FolderOut])
async def list_folders(s: AsyncSession = Depends(get_session)):
    return (await s.execute(select(WatchFolder))).scalars().all()


@router.post("/folders", response_model=FolderOut)
async def add_folder(payload: FolderCreate, s: AsyncSession = Depends(get_session)):
    f = WatchFolder(**payload.model_dump())
    s.add(f)
    await s.commit()
    await s.refresh(f)
    if f.is_active:
        watcher.add(f.id, f.path, asyncio.get_running_loop())
    return f


@router.delete("/folders/{fid}")
async def del_folder(fid: int, s: AsyncSession = Depends(get_session)):
    f = await s.get(WatchFolder, fid)
    if not f:
        raise HTTPException(404)
    watcher.remove(fid)
    await s.delete(f)
    await s.commit()
    return {"ok": True}


@router.post("/folders/{fid}/scan")
async def scan(fid: int, s: AsyncSession = Depends(get_session)):
    f = await s.get(WatchFolder, fid)
    if not f:
        raise HTTPException(404)
    n = await scan_folder_now(f.path)
    return {"added": n}


# ── Unsplash ───────────────────────────────────────────────────────────────
@router.get("/unsplash/search")
async def unsplash_search(q: str = Query(...), per_page: int = 20):
    return await unsplash.search(q, per_page)


@router.post("/unsplash/import", response_model=ImageOut)
async def unsplash_import(payload: ImportPayload):
    if not payload.id:
        raise HTTPException(400, "id required")
    info = await unsplash.get(payload.id)
    if not info:
        raise HTTPException(404)
    img = await download_and_register(
        info["url"], "unsplash", f"unsplash_{info['id']}.jpg",
        {"title": info.get("title"), "credit": info.get("credit"),
         "credit_url": info.get("credit_url"), "html": info.get("html")},
    )
    if not img:
        raise HTTPException(500, "download failed")
    return img


# ── NASA APOD ──────────────────────────────────────────────────────────────
@router.get("/nasa/apod")
async def nasa_apod_today():
    res = await nasa_apod.today()
    return res or {}


@router.post("/nasa/apod/import", response_model=ImageOut)
async def nasa_import():
    info = await nasa_apod.today()
    if not info or info.get("unsupported"):
        raise HTTPException(400, "today's APOD not an image")
    img = await download_and_register(
        info["url"], "nasa", f"apod_{info.get('date')}.jpg",
        {"title": info.get("title"), "explanation": info.get("explanation"),
         "date": info.get("date"), "copyright": info.get("copyright")},
    )
    if not img:
        raise HTTPException(500, "download failed")
    return img


# ── Rijksmuseum ────────────────────────────────────────────────────────────
@router.get("/rijksmuseum/search")
async def rijks_search(q: str = Query(...), per_page: int = 20):
    return await rijksmuseum.search(q, per_page)


@router.post("/rijksmuseum/import", response_model=ImageOut)
async def rijks_import(payload: ImportPayload):
    if not payload.id:
        raise HTTPException(400, "id required")
    info = await rijksmuseum.get(payload.id)
    if not info:
        raise HTTPException(404)
    img = await download_and_register(
        info["url"], "rijksmuseum", f"rijks_{info['id']}.jpg",
        {"title": info.get("title"), "credit": info.get("credit"), "html": info.get("html")},
    )
    if not img:
        raise HTTPException(500, "download failed")
    return img


# ── Reddit ─────────────────────────────────────────────────────────────────
@router.get("/reddit/fetch")
async def reddit_fetch(sub: str = Query(...), sort: str = "top", t: str = "week", limit: int = 20):
    return await reddit.fetch(sub, sort, t, limit)


@router.post("/reddit/import", response_model=ImageOut)
async def reddit_import(payload: ImportPayload):
    if not payload.url:
        raise HTTPException(400, "url required")
    meta = payload.meta or {}
    img = await download_and_register(
        payload.url, "reddit", f"reddit_{payload.id or 'img'}.jpg", meta,
    )
    if not img:
        raise HTTPException(500, "download failed")
    return img
