from __future__ import annotations
import httpx
from ...config import settings


async def search(query: str, per_page: int = 20) -> list[dict]:
    if not settings.RIJKSMUSEUM_API_KEY:
        return []
    url = "https://www.rijksmuseum.nl/api/en/collection"
    params = {
        "key": settings.RIJKSMUSEUM_API_KEY,
        "q": query, "ps": per_page,
        "imgonly": "True", "toppieces": "True",
    }
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        j = r.json()
    out = []
    for art in j.get("artObjects", []):
        webimg = art.get("webImage") or {}
        if not webimg.get("url"):
            continue
        out.append({
            "id": art["objectNumber"],
            "url": webimg["url"],
            "thumb": (art.get("headerImage") or webimg).get("url"),
            "title": art.get("title"),
            "credit": art.get("principalOrFirstMaker"),
            "html": art.get("links", {}).get("web"),
        })
    return out


async def get(object_number: str) -> dict | None:
    if not settings.RIJKSMUSEUM_API_KEY:
        return None
    url = f"https://www.rijksmuseum.nl/api/en/collection/{object_number}"
    params = {"key": settings.RIJKSMUSEUM_API_KEY}
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(url, params=params)
        if r.status_code != 200:
            return None
        j = r.json()
    art = j.get("artObject") or {}
    webimg = art.get("webImage") or {}
    if not webimg.get("url"):
        return None
    return {
        "id": art.get("objectNumber"),
        "url": webimg["url"],
        "title": art.get("title"),
        "credit": art.get("principalOrFirstMaker"),
        "html": (art.get("links") or {}).get("web"),
    }
