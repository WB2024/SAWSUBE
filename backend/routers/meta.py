from __future__ import annotations
import os
import socket
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..config import settings
from ..database import get_session
from ..models.history import History
from ..models.image import Image, TVImage
from ..models.tv import TV
from ..models.schedule import Schedule

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/server-ips")
async def server_ips():
    """Return all non-loopback IPv4 addresses the server is reachable on."""
    ips: list[str] = []
    try:
        # Use getaddrinfo to get all addresses for the hostname
        hostname = socket.gethostname()
        results = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for r in results:
            ip = r[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    if not ips:
        # Fallback: connect to an external addr to find outbound IP
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ips = [s.getsockname()[0]]
        except Exception:
            pass
    return {"ips": ips}


@router.get("/history")
async def history(tv_id: int | None = Query(None), limit: int = 50,
                  s: AsyncSession = Depends(get_session)):
    q = select(History).order_by(History.shown_at.desc()).limit(limit)
    if tv_id is not None:
        q = q.where(History.tv_id == tv_id)
    rows = (await s.execute(q)).scalars().all()
    return [{"id": r.id, "tv_id": r.tv_id, "image_id": r.image_id,
             "shown_at": r.shown_at, "trigger": r.trigger} for r in rows]


@router.get("/stats")
async def stats(s: AsyncSession = Depends(get_session)):
    img_count = (await s.execute(select(func.count(Image.id)))).scalar_one()
    tv_count = (await s.execute(select(func.count(TV.id)))).scalar_one()
    on_tv = (await s.execute(select(func.count(TVImage.id)).where(TVImage.is_on_tv.is_(True)))).scalar_one()
    sched_active = (await s.execute(select(func.count(Schedule.id)).where(Schedule.is_active.is_(True)))).scalar_one()
    storage = 0
    for root, _, files in os.walk(settings.IMAGE_FOLDER):
        for f in files:
            try:
                storage += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return {
        "images": img_count, "tvs": tv_count,
        "images_on_tv": on_tv, "schedules_active": sched_active,
        "storage_bytes": storage,
    }
