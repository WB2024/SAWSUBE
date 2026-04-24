from __future__ import annotations
import httpx

# Openverse (openverse.org) aggregates Creative Commons licensed content from
# Flickr, Wikimedia, museums, and dozens of other sources. No API key required.
# Docs: https://api.openverse.org/v1/

_BASE = "https://api.openverse.org/v1/images/"
_USER_AGENT = "SAWSUBE/1.0 (self-hosted art manager)"

CATEGORIES = ("", "photograph", "illustration", "digitized_artwork")
LICENSE_TYPES = ("", "commercial", "modification", "creative_commons", "public_domain")
ASPECT_RATIOS = ("", "wide", "tall", "square")
SIZES = ("", "large", "medium", "small")


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

    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as c:
        r = await c.get(_BASE, params=params)
        r.raise_for_status()
        j = r.json()

    out = []
    for item in j.get("results", []):
        # Use full-size URL, fall back to thumbnail for display
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
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
    }
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
