from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_session
from ..models.tv import TV
from ..models.image import TVImage, Image
from ..schemas import ArtSettings, MatteSet, CurrentSet
from ..services.tv_manager import tv_manager

router = APIRouter(prefix="/api/tvs/{tv_id}/art", tags=["art"])


@router.get("/settings")
async def get_settings(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    return await tv_manager.get_settings(tv)


@router.post("/settings")
async def set_settings(tv_id: int, payload: ArtSettings, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    return await tv_manager.apply_settings(tv, payload.model_dump(exclude_none=True))


@router.get("/mattes")
async def list_mattes(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    return await tv_manager.list_mattes(tv)


async def _tracked_by_remote_id(s: AsyncSession, tv_id: int) -> dict[str, TVImage]:
    # only rows SAWSUBE believes are still on the TV: the TV may reuse a content_id
    # after deletion, and an old removed row must not claim the new content
    rows = (await s.execute(
        select(TVImage).where(TVImage.tv_id == tv_id, TVImage.is_on_tv.is_(True),
                              TVImage.remote_id.is_not(None))
    )).scalars().all()
    return {r.remote_id: r for r in rows}


@router.get("/available")
async def list_available(tv_id: int, category: str | None = None,
                         s: AsyncSession = Depends(get_session)):
    """Everything stored on the Frame, straight from the TV (not just SAWSUBE uploads).

    category: optional TV category id — 'MY-C0002' (My Photos), 'MY-C0004' (Favourites),
    'MY-C0008' (Art Store).
    """
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    items = await tv_manager.list_images(tv, category=category or None)
    if items is None:
        raise HTTPException(502, "could not query TV (offline, not paired, or art service busy)")
    tracked = await _tracked_by_remote_id(s, tv_id)
    out = []
    for it in items:
        cid = it.get("content_id")
        ti = tracked.get(cid) if cid else None
        out.append({
            **it,
            "tv_image_id": ti.id if ti else None,
            "image_id": ti.image_id if ti else None,
        })
    return out


@router.post("/available/{content_id}/show")
async def show_available(tv_id: int, content_id: str, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    ok = await tv_manager.select_image(tv, content_id, show=True)
    return {"ok": ok}


@router.delete("/available/{content_id}")
async def delete_available(tv_id: int, content_id: str, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    if not await tv_manager.delete_image(tv, content_id):
        return {"ok": False}
    # samsungtvws doesn't check the TV's reply to delete_image_list (a timeout looks like
    # success), so confirm the content is really gone before touching our records
    remaining = await tv_manager.list_images(tv)
    if remaining is None:
        raise HTTPException(502, "delete sent, but could not confirm with the TV — reload to check")
    if any(it.get("content_id") == content_id for it in remaining):
        return {"ok": False}
    rows = (await s.execute(
        select(TVImage).where(TVImage.tv_id == tv_id, TVImage.remote_id == content_id,
                              TVImage.is_on_tv.is_(True))
    )).scalars().all()
    for r in rows:
        r.is_on_tv = False
    await s.commit()
    return {"ok": True}


@router.post("/reconcile")
async def reconcile(tv_id: int, s: AsyncSession = Depends(get_session)):
    """Mark SAWSUBE-tracked images that no longer exist on the TV as removed."""
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    items = await tv_manager.list_images(tv)
    if items is None:
        raise HTTPException(502, "could not query TV (offline, not paired, or art service busy)")
    on_tv = {it.get("content_id") for it in items if it.get("content_id")}
    rows = (await s.execute(
        select(TVImage).where(TVImage.tv_id == tv_id, TVImage.is_on_tv.is_(True))
    )).scalars().all()
    removed = 0
    for r in rows:
        if not r.remote_id or r.remote_id not in on_tv:
            r.is_on_tv = False
            removed += 1
    await s.commit()
    return {"on_tv": len(on_tv), "tracked": len(rows), "marked_removed": removed}


@router.post("/current")
async def set_current(tv_id: int, payload: CurrentSet, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    ti = await s.get(TVImage, payload.tv_image_id)
    if not ti or ti.tv_id != tv_id or not ti.remote_id:
        raise HTTPException(404, "tv_image not found")
    ok = await tv_manager.select_image(tv, ti.remote_id, show=True)
    return {"ok": ok}


@router.get("/current")
async def get_current(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    cur = await tv_manager.get_current(tv)
    return cur or {}


@router.post("/matte/{tv_image_id}")
async def set_matte(tv_id: int, tv_image_id: int, payload: MatteSet, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    ti = await s.get(TVImage, tv_image_id)
    if not tv or not ti or ti.tv_id != tv_id or not ti.remote_id:
        raise HTTPException(404)
    ok = await tv_manager.set_matte(tv, ti.remote_id, payload.matte)
    if ok:
        ti.matte = payload.matte
        await s.commit()
    return {"ok": ok}
