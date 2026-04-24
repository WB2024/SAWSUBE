from __future__ import annotations
import asyncio
import time
import httpx
from ...config import settings

# Openverse (openverse.org) aggregates Creative Commons licensed content from
# Flickr, Wikimedia, museums, and dozens of other sources.
# Free registration at: https://api.openverse.org/v1/#tag/auth
# Set OPENVERSE_CLIENT_ID and OPENVERSE_CLIENT_SECRET in .env

_BASE = "https://api.openverse.org/v1/images/"
_TOKEN_URL = "https://api.openverse.org/v1/auth_tokens/token/"
_USER_AGENT = "SAWSUBE/1.0 (self-hosted Samsung Frame art manager)"

CATEGORIES = ("", "photograph", "illustration", "digitized_artwork")
LICENSE_TYPES = ("", "commercial", "modification", "creative_commons", "public_domain")
ASPECT_RATIOS = ("", "wide", "tall", "square")
SIZES = ("", "large", "medium", "small")

# Token cache
_token: str = ""
_token_expires: float = 0.0
_token_lock = asyncio.Lock()


async def _get_auth_headers() -> dict:
    """Return auth headers. Fetches/refreshes token if client credentials are configured."""
    global _token, _token_expires

    client_id = settings.OPENVERSE_CLIENT_ID
    client_secret = settings.OPENVERSE_CLIENT_SECRET

    if not client_id or not client_secret:
        # No credentials — anonymous request (may 401 if Openverse tightens policy)
        return {"User-Agent": _USER_AGENT, "Accept": "application/json"}

    async with _token_lock:
        # Refresh if missing or within 60s of expiry
        if not _token or time.monotonic() >= _token_expires - 60:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.post(
                    _TOKEN_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                    },
                    headers={"User-Agent": _USER_AGENT},
                )
                r.raise_for_status()
                j = r.json()
            _token = j["access_token"]
            _token_expires = time.monotonic() + int(j.get("expires_in", 43200))

    return {
        "Authorization": f"Bearer {_token}",
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
    }


async def search(
    q: str,
    page_size: int = 20,
    category: str = "",
    license_type: str = "",
    aspect_ratio: str = "wide",
    size: str = "large",
) -> list[dict]:
    params: dict = {
        "q": q,
        "page_size": min(max(int(page_size), 1), 100),
        "mature": "false",
        "filter_dead": "true",
    }
    if category and category in CATEGORIES:
        params["category"] = category
    if license_type and license_type in LICENSE_TYPES:
        params["license_type"] = license_type
    if aspect_ratio and aspect_ratio in ASPECT_RATIOS:
        params["aspect_ratio"] = aspect_ratio
    if size and size in SIZES:
        params["size"] = size

    headers = await _get_auth_headers()
    async with httpx.AsyncClient(timeout=20.0, headers=headers) as c:
        r = await c.get(_BASE, params=params)
        r.raise_for_status()
        j = r.json()

    out = []
    for item in j.get("results", []):
        url = item.get("url", "")
        thumb = item.get("thumbnail") or url
        if not url:
            continue
        out.append({
            "id": item.get("id", ""),
            "url": url,
            "thumb": thumb,
            "title": item.get("title") or "Untitled",
            "credit": item.get("creator") or "",
            "credit_url": item.get("creator_url") or "",
            "html": item.get("foreign_landing_url") or "",
            "license": item.get("license", ""),
            "source": item.get("source", ""),
            "width": item.get("width"),
            "height": item.get("height"),
        })
    return out


async def get(image_id: str) -> dict | None:
    """Fetch a single image by its Openverse UUID for the import step."""
    headers = await _get_auth_headers()
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as c:
        r = await c.get(f"{_BASE}{image_id}/")
        if r.status_code != 200:
            return None
        item = r.json()

    url = item.get("url", "")
    if not url:
        return None

    return {
        "id": item.get("id", ""),
        "url": url,
        "title": item.get("title") or "Untitled",
        "credit": item.get("creator") or "",
        "credit_url": item.get("creator_url") or "",
        "html": item.get("foreign_landing_url") or "",
        "license": item.get("license", ""),
        "source": item.get("source", ""),
        "filetype": item.get("filetype") or "",
    }
