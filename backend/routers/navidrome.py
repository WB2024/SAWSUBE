from __future__ import annotations
import io
import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from ..config import settings

router = APIRouter(prefix="/api/navidrome", tags=["navidrome"])


@router.get("/image")
async def proxy_navidrome_image(
    id: str = Query(..., description="Navidrome cover art ID (e.g. al-xxx, ar-xxx, pl-xxx)"),
    size: int | None = Query(None, ge=50, le=1200, description="Resize to this square size (px)"),
):
    """Proxy & optionally resize a cover art image from Navidrome.
    30-day cache headers; converts WebP → JPEG so Tizen WebKit can render it."""
    if not settings.NAVIDROME_URL:
        raise HTTPException(status_code=503, detail="NAVIDROME_URL not configured")

    nd_base = settings.NAVIDROME_URL.rstrip("/")
    params: dict[str, str] = {
        "u": settings.NAVIDROME_USERNAME,
        "p": settings.NAVIDROME_PASSWORD,
        "v": "1.16.1",
        "c": "sawsube",
        "id": id,
    }
    if size:
        params["size"] = str(size)

    target_url = f"{nd_base}/rest/getCoverArt.view"

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            res = await client.get(target_url, params=params)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach Navidrome: {e}")

    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail="Navidrome image request failed")

    content = res.content
    content_type = res.headers.get("content-type", "image/jpeg")

    # Tizen WebKit can struggle with webp — convert to jpeg
    if content_type.startswith("image/") and (content_type == "image/webp" or size):
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(content))
            if size and (img.width > size or img.height > size):
                img.thumbnail((size, size), Image.LANCZOS)
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=True)
            content = buf.getvalue()
            content_type = "image/jpeg"
        except Exception:
            pass

    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=2592000",
            "X-Content-Type-Options": "nosniff",
        },
    )
