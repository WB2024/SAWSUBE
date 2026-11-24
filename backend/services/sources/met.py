"""The Met Open Access: public-domain (CC0) paintings, no API key needed.

https://metmuseum.github.io/ — search uses /v1.1/search (the v1 search
endpoint was retired on 2026-10-01); object details still live under /v1.
"""
from __future__ import annotations
import asyncio
import logging
import httpx

log = logging.getLogger(__name__)

_API = "https://collectionapi.metmuseum.org/public/collection"
OBJECT_URL = _API + "/v1/objects/{id}"
SEARCH_URL = _API + "/v1.1/search"
# The Met API answers 403 to httpx's default User-Agent.
_USER_AGENT = "SAWSUBE/1.0 (+https://github.com/WB2024/SAWSUBE)"
_CANDIDATES = 60   # object ids fetched per search; many are filtered out
_CONCURRENCY = 4   # be polite: the API is rate limited (~80 req/s)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30.0, follow_redirects=True,
                             headers={"User-Agent": _USER_AGENT})


def normalize(d: dict) -> dict | None:
    """Keep only public-domain paintings that have a primary image."""
    if not d.get("isPublicDomain") or not d.get("primaryImage") or d.get("objectName") != "Painting":
        return None
    return {
        "id": str(d["objectID"]),
        "title": d.get("title") or "",
        "credit": d.get("artistDisplayName") or "",
        "date": d.get("objectDate") or "",
        "url": d["primaryImage"],
        "thumb": d.get("primaryImageSmall") or d["primaryImage"],
        "html": d.get("objectURL") or "",
        "license": "CC0",
        "source": "The Met Open Access",
    }


async def get(object_id: str | int) -> dict | None:
    async with _client() as c:
        r = await c.get(OBJECT_URL.format(id=int(object_id)))
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return normalize(r.json())


async def search(q: str, per_page: int = 20) -> list[dict]:
    async with _client() as c:
        r = await c.get(SEARCH_URL, params={"q": q, "hasImages": "true", "medium": "Paintings",
                                            "limit": _CANDIDATES})
        r.raise_for_status()
        ids = (r.json().get("objectIDs") or [])[:_CANDIDATES]
        sem = asyncio.Semaphore(_CONCURRENCY)

        async def fetch(oid: int) -> dict | None:
            async with sem:
                try:
                    resp = await c.get(OBJECT_URL.format(id=int(oid)))
                    resp.raise_for_status()
                    return normalize(resp.json())
                except (httpx.HTTPError, ValueError) as e:
                    log.debug("met: object %s skipped: %s", oid, e)
                    return None

        items = await asyncio.gather(*(fetch(oid) for oid in ids))
    return [x for x in items if x][:per_page]
