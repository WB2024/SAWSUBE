from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_session
from ..models.schedule import Schedule
from ..schemas import ScheduleCreate, ScheduleOut
from ..services.scheduler import install_schedule, remove_schedule, fire_schedule

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


@router.get("", response_model=list[ScheduleOut])
async def list_schedules(s: AsyncSession = Depends(get_session)):
    return (await s.execute(select(Schedule))).scalars().all()


@router.post("", response_model=ScheduleOut)
async def create(payload: ScheduleCreate, s: AsyncSession = Depends(get_session)):
    sc = Schedule(**payload.model_dump())
    s.add(sc)
    await s.commit()
    await s.refresh(sc)
    await install_schedule(sc)
    return sc


@router.put("/{sched_id}", response_model=ScheduleOut)
async def update(sched_id: int, payload: ScheduleCreate, s: AsyncSession = Depends(get_session)):
    sc = await s.get(Schedule, sched_id)
    if not sc:
        raise HTTPException(404)
    for k, v in payload.model_dump().items():
        setattr(sc, k, v)
    await s.commit()
    await s.refresh(sc)
    await install_schedule(sc)
    return sc


@router.delete("/{sched_id}")
async def delete(sched_id: int, s: AsyncSession = Depends(get_session)):
    sc = await s.get(Schedule, sched_id)
    if not sc:
        raise HTTPException(404)
    await remove_schedule(sched_id)
    await s.delete(sc)
    await s.commit()
    return {"ok": True}


@router.post("/{sched_id}/toggle")
async def toggle(sched_id: int, s: AsyncSession = Depends(get_session)):
    sc = await s.get(Schedule, sched_id)
    if not sc:
        raise HTTPException(404)
    sc.is_active = not sc.is_active
    await s.commit()
    await install_schedule(sc)
    return {"is_active": sc.is_active}


@router.post("/{sched_id}/trigger")
async def trigger(sched_id: int):
    await fire_schedule(sched_id)
    return {"ok": True}
