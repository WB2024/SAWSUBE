from __future__ import annotations
import asyncio
import logging
import os
import random
from datetime import datetime, time as dtime
from sqlalchemy import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from ..database import SessionLocal
from ..models.schedule import Schedule
from ..models.image import Image, TVImage
from ..models.tv import TV
from ..models.history import History
from .tv_manager import tv_manager
from .image_processor import process_image
from .ws_manager import ws_manager

log = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
RECENT_EXCLUDE = 5  # exclude last N images


def _in_window(sched: Schedule, now: datetime) -> bool:
    days = [int(x) for x in (sched.days_of_week or "0,1,2,3,4,5,6").split(",") if x.strip().isdigit()]
    if now.weekday() not in days:
        return False
    if sched.time_from and sched.time_to:
        t = now.time()
        if sched.time_from <= sched.time_to:
            return sched.time_from <= t <= sched.time_to
        # window spans midnight
        return t >= sched.time_from or t <= sched.time_to
    return True


async def _eligible_images(s, sched: Schedule) -> list[Image]:
    q = select(Image)
    sf = sched.source_filter or {}
    if sf.get("favourites_only"):
        q = q.where(Image.is_favourite.is_(True))
    if sf.get("source"):
        q = q.where(Image.source == sf["source"])
    rows = (await s.execute(q)).scalars().all()
    if sf.get("tag"):
        tag = sf["tag"].lower()
        rows = [r for r in rows if r.tags and tag in r.tags.lower()]
    # exclude recently shown
    recent = (await s.execute(
        select(History.image_id).where(History.tv_id == sched.tv_id)
        .order_by(History.shown_at.desc()).limit(RECENT_EXCLUDE)
    )).scalars().all()
    if rows and len(rows) > len(recent):
        rows = [r for r in rows if r.id not in recent]
    return rows


async def fire_schedule(sched_id: int) -> None:
    async with SessionLocal() as s:
        sched = await s.get(Schedule, sched_id)
        if not sched or not sched.is_active:
            return
        if not _in_window(sched, datetime.now()):
            return
        tv = await s.get(TV, sched.tv_id)
        if not tv:
            return
        imgs = await _eligible_images(s, sched)
        if not imgs:
            return
        if sched.mode == "sequential":
            sched.last_index = (sched.last_index + 1) % len(imgs)
            img = imgs[sched.last_index]
        elif sched.mode == "weighted":
            weights = [3 if i.is_favourite else 1 for i in imgs]
            img = random.choices(imgs, weights=weights, k=1)[0]
        else:
            img = random.choice(imgs)

        # Ensure on TV
        ti = (await s.execute(
            select(TVImage).where(TVImage.tv_id == tv.id, TVImage.image_id == img.id, TVImage.is_on_tv.is_(True))
        )).scalar_one_or_none()
        if ti is None or not ti.remote_id:
            processed_path = img.processed_path
            if not processed_path or not os.path.exists(processed_path):
                processed_path, w, h = await process_image(img.local_path, img.file_hash)
                img.processed_path = processed_path
                img.width, img.height = w, h
                await s.commit()
            remote_id = await tv_manager.upload_image(tv, processed_path)
            if not remote_id:
                log.warning("Schedule %s: upload failed", sched_id)
                return
            ti = TVImage(tv_id=tv.id, image_id=img.id, remote_id=remote_id, is_on_tv=True)
            s.add(ti)
            await s.commit()

        ok = await tv_manager.select_image(tv, ti.remote_id, show=True)
        if ok:
            s.add(History(tv_id=tv.id, image_id=img.id, trigger="schedule"))
            await s.commit()
            await ws_manager.broadcast({
                "type": "schedule_fired", "schedule_id": sched.id, "image_id": img.id, "tv_id": tv.id,
            })


def _job_id(sched_id: int) -> str:
    return f"sched_{sched_id}"


async def install_schedule(sched: Schedule) -> None:
    jid = _job_id(sched.id)
    if scheduler.get_job(jid):
        scheduler.remove_job(jid)
    if not sched.is_active:
        return
    scheduler.add_job(
        fire_schedule, IntervalTrigger(minutes=max(1, sched.interval_mins)),
        args=[sched.id], id=jid, replace_existing=True,
    )


async def remove_schedule(sched_id: int) -> None:
    jid = _job_id(sched_id)
    if scheduler.get_job(jid):
        scheduler.remove_job(jid)


async def load_all() -> None:
    async with SessionLocal() as s:
        rows = (await s.execute(select(Schedule))).scalars().all()
        for sc in rows:
            await install_schedule(sc)
    if not scheduler.running:
        scheduler.start()


async def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
