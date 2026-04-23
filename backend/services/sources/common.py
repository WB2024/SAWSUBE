from __future__ import annotations
import os
import logging
from datetime import datetime
import httpx
from sqlalchemy import select
from ...config import settings
from ...database import SessionLocal
from ...models.image import Image
from ..image_processor import sha256_file, process_image, make_thumbnail

log = logging.getLogger(__name__)


async def download_and_register(url: str, source: str, filename: str, meta: dict) -> Image | None:
    dest_dir = os.path.join(settings.IMAGE_FOLDER, source)
    os.makedirs(dest_dir, exist_ok=True)
    safe_fn = "".join(c for c in filename if c.isalnum() or c in "._-") or "image.jpg"
    if not safe_fn.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        safe_fn += ".jpg"
    dest = os.path.join(dest_dir, safe_fn)
    n = 1
    base, ext = os.path.splitext(dest)
    while os.path.exists(dest):
        dest = f"{base}_{n}{ext}"
        n += 1
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        with open(dest, "wb") as f:
            f.write(r.content)
    digest = sha256_file(dest)
    async with SessionLocal() as s:
        existing = (await s.execute(select(Image).where(Image.file_hash == digest))).scalar_one_or_none()
        if existing:
            try:
                os.remove(dest)
            except Exception:
                pass
            return existing
        try:
            processed_path, w, h = await process_image(dest, digest)
            thumb = await make_thumbnail(dest, digest)
        except Exception as e:
            log.warning("process failed: %s", e)
            return None
        img = Image(
            local_path=dest, filename=os.path.basename(dest),
            file_hash=digest, file_size=os.path.getsize(dest),
            width=w, height=h, source=source, source_meta=meta,
            uploaded_at=datetime.utcnow(),
            processed_path=processed_path, thumbnail_path=thumb,
        )
        s.add(img)
        await s.commit()
        await s.refresh(img)
        return img
