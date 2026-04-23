from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_session
from ..models.tv import TV
from ..schemas import TVCreate, TVOut, TVStatus
from ..services.tv_manager import tv_manager, token_path_for, HAS_LIB
from ..services.discovery import discover_tvs

router = APIRouter(prefix="/api/tvs", tags=["tvs"])


@router.get("", response_model=list[TVOut])
async def list_tvs(s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(TV))).scalars().all()
    return rows


@router.post("", response_model=TVOut)
async def add_tv(payload: TVCreate, s: AsyncSession = Depends(get_session)):
    tv = TV(name=payload.name, ip=payload.ip, mac=payload.mac, port=payload.port)
    s.add(tv)
    await s.commit()
    await s.refresh(tv)
    tv.token_path = token_path_for(tv)
    await s.commit()
    return tv


@router.get("/discover")
async def discover():
    return await discover_tvs()


@router.get("/{tv_id}", response_model=TVOut)
async def get_tv(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    return tv


@router.delete("/{tv_id}")
async def delete_tv(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    await tv_manager.remove(tv_id)
    await s.delete(tv)
    await s.commit()
    return {"ok": True}


@router.post("/{tv_id}/pair")
async def pair(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    if not HAS_LIB:
        raise HTTPException(500, "samsungtvws library not installed")
    ok = await tv_manager.pair(tv)
    return {"paired": ok}


@router.get("/{tv_id}/status", response_model=TVStatus)
async def status(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    st = await tv_manager.fetch_status(tv_id)
    import os
    return TVStatus(
        id=tv_id,
        online=st.get("online", False),
        artmode=st.get("artmode"),
        current=st.get("current"),
        paired=os.path.exists(token_path_for(tv)),
        error=st.get("error"),
    )


@router.post("/{tv_id}/power/on")
async def power_on(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    return {"ok": await tv_manager.power_on(tv)}


@router.post("/{tv_id}/power/off")
async def power_off(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    return {"ok": await tv_manager.power_off(tv)}


@router.post("/{tv_id}/artmode/on")
async def artmode_on(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    return {"ok": await tv_manager.set_artmode(tv, True)}


@router.post("/{tv_id}/artmode/off")
async def artmode_off(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    return {"ok": await tv_manager.set_artmode(tv, False)}


@router.get("/{tv_id}/info")
async def info(tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    return await tv_manager.device_info(tv)
