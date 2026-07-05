"""Pixabay API source — photo search and single-photo fetch.

Auth: `key` query parameter (not a header).
Docs: https://pixabay.com/api/docs/
"""
from __future__ import annotations
import httpx
from ...config import settings

_BASE = "https://pixabay.com/api/"


def _normalise(p: dict) -> dict:
    user = p.get("user", "")
    user_id = p.get("user_id", "")
    credit_url = f"https://pixabay.com/users/{user}-{user_id}/" if user and user_id else None
    # largeImageURL (≤1280px) is best for TV upload; webformatURL (≤640px) for thumb
    url = p.get("largeImageURL") or p.get("webformatURL")
    thumb = p.get("webformatURL") or p.get("previewURL")
    # Build a title from tags if no explicit title field
    tags_raw = p.get("tags", "")
    title = tags_raw.split(",")[0].strip().title() if tags_raw else f"Pixabay photo {p['id']}"
    return {
        "id": str(p["id"]),
        "url": url,
        "thumb": thumb,
        "width": p.get("imageWidth") or p.get("webformatWidth"),
        "height": p.get("imageHeight") or p.get("webformatHeight"),
        "title": title,
        "credit": user or None,
        "credit_url": credit_url,
        "html": p.get("pageURL"),
    }


async def search(query: str, per_page: int = 20, page: int = 1) -> dict:
    if not settings.PIXABAY_API_KEY:
        return {"items": [], "next": None}
    page = max(1, int(page))
    per_page = max(3, min(int(per_page), 200))
    params = {
        "key": settings.PIXABAY_API_KEY,
        "q": query,
        "image_type": "photo",
        "orientation": "horizontal",
        "safesearch": "true",
        "per_page": per_page,
        "page": page,
        "order": "popular",
    }
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(_BASE, params=params)
        r.raise_for_status()
        j = r.json()
    items = [_normalise(p) for p in j.get("hits", [])]
    # totalHits is how many results the API will actually serve (max 500)
    has_more = items and page * per_page < int(j.get("totalHits") or 0)
    return {"items": items, "next": str(page + 1) if has_more else None}


async def get(photo_id: str) -> dict | None:
    if not settings.PIXABAY_API_KEY:
        return None
    params = {"key": settings.PIXABAY_API_KEY, "id": photo_id}
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(_BASE, params=params)
        if r.status_code != 200:
            return None
        hits = r.json().get("hits", [])
    if not hits:
        return None
    return _normalise(hits[0])
