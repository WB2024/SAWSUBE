from __future__ import annotations
import httpx
from ...config import settings


async def search(query: str, per_page: int = 20) -> list[dict]:
    if not settings.UNSPLASH_API_KEY:
        return []
    url = "https://api.unsplash.com/search/photos"
    params = {"query": query, "per_page": per_page, "orientation": "landscape"}
    headers = {"Authorization": f"Client-ID {settings.UNSPLASH_API_KEY}"}
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(url, params=params, headers=headers)
        r.raise_for_status()
        j = r.json()
    return [
        {
            "id": p["id"],
            "url": p["urls"]["full"],
            "thumb": p["urls"]["small"],
            "width": p["width"],
            "height": p["height"],
            "title": p.get("description") or p.get("alt_description") or "Unsplash photo",
            "credit": (p.get("user") or {}).get("name"),
            "credit_url": (p.get("user") or {}).get("links", {}).get("html"),
            "html": p.get("links", {}).get("html"),
        }
        for p in j.get("results", [])
    ]


async def get(photo_id: str) -> dict | None:
    if not settings.UNSPLASH_API_KEY:
        return None
    url = f"https://api.unsplash.com/photos/{photo_id}"
    headers = {"Authorization": f"Client-ID {settings.UNSPLASH_API_KEY}"}
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(url, headers=headers)
        if r.status_code != 200:
            return None
        p = r.json()
    return {
        "id": p["id"],
        "url": p["urls"]["full"],
        "title": p.get("description") or p.get("alt_description") or "Unsplash photo",
        "credit": (p.get("user") or {}).get("name"),
        "credit_url": (p.get("user") or {}).get("links", {}).get("html"),
        "html": p.get("links", {}).get("html"),
    }
