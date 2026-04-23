from __future__ import annotations
import os
from datetime import datetime
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..config import settings
from ..database import get_session
from ..models.image import Image, TVImage
from ..models.tv import TV
from ..models.history import History
from ..schemas import ImageOut, TagsUpdate, TVImageOut
from ..services.image_processor import (
    sha256_file, process_image, make_thumbnail, is_supported,
)
from ..services.tv_manager import tv_manager
from ..services.ws_manager import ws_manager

router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("", response_model=list[ImageOut])
async def list_images(
    s: AsyncSession = Depends(get_session),
    source: str | None = Query(None),
    tag: str | None = Query(None),
    favourite: bool | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
    order: str = Query("uploaded_desc"),
):
    qy = select(Image)
    if source:
        qy = qy.where(Image.source == source)
    if favourite is not None:
        qy = qy.where(Image.is_favourite.is_(favourite))
    if q:
        like = f"%{q}%"
        qy = qy.where(Image.filename.ilike(like))
    if order == "name":
        qy = qy.order_by(Image.filename.asc())
    elif order == "size":
        qy = qy.order_by(Image.file_size.desc())
    else:
        qy = qy.order_by(Image.uploaded_at.desc())
    qy = qy.limit(limit).offset(offset)
    rows = (await s.execute(qy)).scalars().all()
    if tag:
        t = tag.lower()
        rows = [r for r in rows if r.tags and t in r.tags.lower()]
    return rows


@router.post("/upload", response_model=list[ImageOut])
async def upload(files: list[UploadFile] = File(...), s: AsyncSession = Depends(get_session)):
    out: list[Image] = []
    dest_dir = os.path.join(settings.IMAGE_FOLDER, "uploads")
    os.makedirs(dest_dir, exist_ok=True)
    for f in files:
        if not f.filename or not is_supported(f.filename):
            continue
        target = os.path.join(dest_dir, f.filename)
        n = 1
        base, ext = os.path.splitext(target)
        while os.path.exists(target):
            target = f"{base}_{n}{ext}"
            n += 1
        with open(target, "wb") as fh:
            while True:
                chunk = await f.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
        digest = sha256_file(target)
        existing = (await s.execute(select(Image).where(Image.file_hash == digest))).scalar_one_or_none()
        if existing:
            try:
                os.remove(target)
            except Exception:
                pass
            out.append(existing)
            continue
        try:
            processed_path, w, h = await process_image(target, digest)
            thumb = await make_thumbnail(target, digest)
        except Exception as e:
            raise HTTPException(400, f"image process failed: {e}")
        img = Image(
            local_path=target, filename=os.path.basename(target),
            file_hash=digest, file_size=os.path.getsize(target),
            width=w, height=h, source="local",
            uploaded_at=datetime.utcnow(),
            processed_path=processed_path, thumbnail_path=thumb,
        )
        s.add(img)
        await s.commit()
        await s.refresh(img)
        await ws_manager.broadcast({"type": "image_added", "image_id": img.id, "filename": img.filename})
        out.append(img)
    return out


@router.delete("/{image_id}")
async def delete_image(image_id: int, also_from_tv: bool = False, s: AsyncSession = Depends(get_session)):
    img = await s.get(Image, image_id)
    if not img:
        raise HTTPException(404)
    if also_from_tv:
        tis = (await s.execute(select(TVImage).where(TVImage.image_id == image_id))).scalars().all()
        for ti in tis:
            tv = await s.get(TV, ti.tv_id)
            if tv and ti.remote_id:
                await tv_manager.delete_image(tv, ti.remote_id)
            ti.is_on_tv = False
        await s.commit()
    await s.delete(img)
    await s.commit()
    return {"ok": True}


@router.post("/{image_id}/favourite")
async def toggle_favourite(image_id: int, s: AsyncSession = Depends(get_session)):
    img = await s.get(Image, image_id)
    if not img:
        raise HTTPException(404)
    img.is_favourite = not img.is_favourite
    await s.commit()
    return {"is_favourite": img.is_favourite}


@router.put("/{image_id}/tags")
async def update_tags(image_id: int, payload: TagsUpdate, s: AsyncSession = Depends(get_session)):
    img = await s.get(Image, image_id)
    if not img:
        raise HTTPException(404)
    img.tags = payload.tags
    await s.commit()
    return {"tags": img.tags}


@router.get("/{image_id}/thumbnail")
async def get_thumbnail(image_id: int, s: AsyncSession = Depends(get_session)):
    img = await s.get(Image, image_id)
    if not img:
        raise HTTPException(404)
    if not img.thumbnail_path or not os.path.exists(img.thumbnail_path):
        path = await make_thumbnail(img.local_path, img.file_hash)
        img.thumbnail_path = path
        await s.commit()
    return FileResponse(img.thumbnail_path, media_type="image/jpeg")


@router.get("/{image_id}/full")
async def get_full(image_id: int, s: AsyncSession = Depends(get_session)):
    img = await s.get(Image, image_id)
    if not img:
        raise HTTPException(404)
    path = img.processed_path or img.local_path
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path)


@router.post("/{image_id}/send/{tv_id}", response_model=TVImageOut)
async def send_to_tv(image_id: int, tv_id: int, display: bool = True,
                     s: AsyncSession = Depends(get_session)):
    img = await s.get(Image, image_id)
    tv = await s.get(TV, tv_id)
    if not img or not tv:
        raise HTTPException(404)
    if not img.processed_path or not os.path.exists(img.processed_path):
        processed_path, w, h = await process_image(img.local_path, img.file_hash)
        img.processed_path = processed_path
        img.width, img.height = w, h
        await s.commit()
    existing = (await s.execute(
        select(TVImage).where(TVImage.tv_id == tv_id, TVImage.image_id == image_id, TVImage.is_on_tv.is_(True))
    )).scalar_one_or_none()
    if existing and existing.remote_id:
        ti = existing
    else:
        remote_id = await tv_manager.upload_image(tv, img.processed_path)
        if not remote_id:
            raise HTTPException(502, "upload to TV failed")
        ti = TVImage(tv_id=tv_id, image_id=image_id, remote_id=remote_id, is_on_tv=True)
        s.add(ti)
        await s.commit()
        await s.refresh(ti)
    if display:
        ok = await tv_manager.select_image(tv, ti.remote_id, show=True)
        if ok:
            s.add(History(tv_id=tv_id, image_id=image_id, trigger="manual"))
            await s.commit()
    return ti


@router.delete("/{image_id}/tv/{tv_id}")
async def remove_from_tv(image_id: int, tv_id: int, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    ti = (await s.execute(
        select(TVImage).where(TVImage.tv_id == tv_id, TVImage.image_id == image_id)
    )).scalar_one_or_none()
    if not tv or not ti:
        raise HTTPException(404)
    if ti.remote_id:
        await tv_manager.delete_image(tv, ti.remote_id)
    ti.is_on_tv = False
    await s.commit()
    return {"ok": True}


@router.get("/tv/{tv_id}", response_model=list[TVImageOut])
async def list_on_tv(tv_id: int, s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(
        select(TVImage).where(TVImage.tv_id == tv_id, TVImage.is_on_tv.is_(True))
    )).scalars().all()
    return rows


@router.get("/tv/{tv_id}/thumbnail/{remote_id}")
async def tv_thumb(tv_id: int, remote_id: str, s: AsyncSession = Depends(get_session)):
    tv = await s.get(TV, tv_id)
    if not tv:
        raise HTTPException(404)
    data = await tv_manager.get_thumbnail(tv, remote_id)
    if not data:
        raise HTTPException(404)
    return Response(content=data, media_type="image/jpeg")
