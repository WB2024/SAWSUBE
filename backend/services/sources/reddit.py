from __future__ import annotations
import asyncio
import httpx
from ...config import settings

_last_call = 0.0
_lock = asyncio.Lock()


async def fetch(sub: str, sort: str = "top", t: str = "week", limit: int = 20) -> list[dict]:
    global _last_call
    async with _lock:
        delay = 2.0 - (asyncio.get_event_loop().time() - _last_call)
        if delay > 0:
            await asyncio.sleep(delay)
        url = f"https://www.reddit.com/r/{sub}/{sort}.json"
        params = {"limit": limit, "t": t}
        headers = {"User-Agent": settings.REDDIT_USER_AGENT}
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as c:
            r = await c.get(url, params=params)
            r.raise_for_status()
            j = r.json()
        _last_call = asyncio.get_event_loop().time()
    out = []
    for child in (j.get("data") or {}).get("children", []):
        d = child.get("data") or {}
        if d.get("post_hint") != "image":
            continue
        out.append({
            "id": d.get("id"),
            "url": d.get("url_overridden_by_dest") or d.get("url"),
            "thumb": d.get("thumbnail") if str(d.get("thumbnail", "")).startswith("http") else d.get("url"),
            "title": d.get("title"),
            "credit": d.get("author"),
            "html": "https://www.reddit.com" + d.get("permalink", ""),
            "subreddit": d.get("subreddit"),
        })
    return out
