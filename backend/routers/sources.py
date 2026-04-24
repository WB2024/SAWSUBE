from __future__ import annotations
import asyncio
import os
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_session
from ..models.folder import WatchFolder
from ..schemas import FolderCreate, FolderOut, ImportPayload, ImageOut
from ..services.watcher import watcher, scan_folder_now
from ..services.sources import unsplash, nasa_apod, rijksmuseum, reddit, reddit_gallery, pexels, pixabay, openverse
from ..services.sources.common import download_and_register

router = APIRouter(prefix="/api/sources", tags=["sources"])


# ── Folders ────────────────────────────────────────────────────────────────
@router.get("/folders", response_model=list[FolderOut])
async def list_folders(s: AsyncSession = Depends(get_session)):
    return (await s.execute(select(WatchFolder))).scalars().all()


@router.post("/folders", response_model=FolderOut)
async def add_folder(payload: FolderCreate, s: AsyncSession = Depends(get_session)):
    path = os.path.abspath(payload.path or "")
    if not path or not os.path.isdir(path):
        raise HTTPException(400, "path does not exist or is not a directory")
    f = WatchFolder(path=path, is_active=payload.is_active, auto_display=payload.auto_display)
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


# ── Pexels ────────────────────────────────────────────────────────────────
@router.get("/pexels/search")
async def pexels_search(q: str = Query(...), per_page: int = 20):
    return await pexels.search(q, per_page)


@router.post("/pexels/import", response_model=ImageOut)
async def pexels_import(payload: ImportPayload):
    if not payload.id:
        raise HTTPException(400, "id required")
    info = await pexels.get(payload.id)
    if not info:
        raise HTTPException(404)
    img = await download_and_register(
        info["url"], "pexels", f"pexels_{info['id']}.jpg",
        {"title": info.get("title"), "credit": info.get("credit"),
         "credit_url": info.get("credit_url"), "html": info.get("html")},
    )
    if not img:
        raise HTTPException(500, "download failed")
    return img


# ── Pixabay ──────────────────────────────────────────────────────────────
@router.get("/pixabay/search")
async def pixabay_search(q: str = Query(...), per_page: int = 20):
    return await pixabay.search(q, per_page)


@router.post("/pixabay/import", response_model=ImageOut)
async def pixabay_import(payload: ImportPayload):
    if not payload.id:
        raise HTTPException(400, "id required")
    info = await pixabay.get(payload.id)
    if not info:
        raise HTTPException(404)
    img = await download_and_register(
        info["url"], "pixabay", f"pixabay_{info['id']}.jpg",
        {"title": info.get("title"), "credit": info.get("credit"),
         "credit_url": info.get("credit_url"), "html": info.get("html")},
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


# ── Reddit Galleries ────────────────────────────────────────────────────────
@router.get("/reddit-gallery/fetch")
async def reddit_gallery_fetch(sub: str = Query(...), sort: str = "top", t: str = "week", limit: int = 25):
    return await reddit_gallery.fetch(sub, sort, t, limit)


@router.post("/reddit-gallery/import", response_model=ImageOut)
async def reddit_gallery_import(payload: ImportPayload):
    if not payload.url:
        raise HTTPException(400, "url required")
    meta = payload.meta or {}
    ext = meta.get("ext", "jpg")
    img = await download_and_register(
        payload.url, "reddit", f"reddit_{payload.id or 'img'}.{ext}", meta,
    )
    if not img:
        raise HTTPException(500, "download failed")
    return img


# ── Openverse ───────────────────────────────────────────────────────────────
@router.get("/openverse/search")
async def openverse_search(
    q: str = Query(...),
    page_size: int = 20,
    category: str = "",
    license_type: str = "",
    aspect_ratio: str = "wide",
    size: str = "large",
):
    return await openverse.search(q, page_size, category, license_type, aspect_ratio, size)


@router.post("/openverse/import", response_model=ImageOut)
async def openverse_import(payload: ImportPayload):
    if not payload.id:
        raise HTTPException(400, "id required")
    info = await openverse.get(payload.id)
    if not info:
        raise HTTPException(404)
    ext = info.get("filetype") or (info["url"].rsplit(".", 1)[-1].split("?")[0] or "jpg")[:4]
    img = await download_and_register(
        info["url"], "openverse", f"openverse_{info['id']}.{ext}",
        {"title": info.get("title"), "credit": info.get("credit"),
         "credit_url": info.get("credit_url"), "html": info.get("html"),
         "license": info.get("license"), "source": info.get("source")},
    )
    if not img:
        raise HTTPException(500, "download failed")
    return img
