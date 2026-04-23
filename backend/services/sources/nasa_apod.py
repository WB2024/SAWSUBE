from __future__ import annotations
import httpx


async def today() -> dict | None:
    url = "https://api.nasa.gov/planetary/apod"
    params = {"api_key": "DEMO_KEY"}
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(url, params=params)
        if r.status_code != 200:
            return None
        j = r.json()
    if j.get("media_type") != "image":
        return {"unsupported": True, "title": j.get("title"), "media_type": j.get("media_type")}
    return {
        "url": j.get("hdurl") or j.get("url"),
        "title": j.get("title"),
        "explanation": j.get("explanation"),
        "date": j.get("date"),
        "copyright": j.get("copyright"),
    }
