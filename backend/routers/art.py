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
