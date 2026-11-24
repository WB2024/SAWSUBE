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


MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024  # far above any real artwork, stops runaway downloads


class DownloadTooLarge(Exception):
    pass


def _http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30.0, follow_redirects=True)


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


async def _download(url: str, dest: str) -> None:
    """Stream ``url`` to ``dest``, refusing anything over MAX_DOWNLOAD_BYTES."""
    async with _http_client() as client:
        async with client.stream("GET", url) as r:
            r.raise_for_status()
            declared = r.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_DOWNLOAD_BYTES:
                raise DownloadTooLarge(f"{declared} bytes")
            size = 0
            with open(dest, "wb") as f:
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise DownloadTooLarge(f"more than {MAX_DOWNLOAD_BYTES} bytes")
                    f.write(chunk)


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
    try:
        await _download(url, dest)
    except (httpx.HTTPError, DownloadTooLarge) as e:
        log.warning("download failed for %s: %s", url, e)
        _remove_quietly(dest)
        return None
    except BaseException:
        _remove_quietly(dest)
        raise
    digest = sha256_file(dest)
    async with SessionLocal() as s:
        existing = (await s.execute(select(Image).where(Image.file_hash == digest))).scalar_one_or_none()
        if existing:
            _remove_quietly(dest)
            return existing
        try:
            processed_path, w, h = await process_image(dest, digest)
            thumb = await make_thumbnail(dest, digest)
        except Exception as e:
            # not a decodable image (HTML error page, truncated file...): don't keep it
            log.warning("process failed for %s: %s", url, e)
            _remove_quietly(dest)
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
