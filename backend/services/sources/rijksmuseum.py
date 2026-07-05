from __future__ import annotations
import asyncio
import httpx

# Rijksmuseum's new Search API (https://data.rijksmuseum.nl/docs/search) is
# public and needs no API key. Search returns Linked Open Data identifiers;
# each is resolved (object -> VisualItem -> DigitalObject) to get metadata
# and the IIIF image URL.
SEARCH_URL = "https://data.rijksmuseum.nl/search/collection"
RESOLVE_URL = "https://id.rijksmuseum.nl/{oid}"
HEADERS = {"Accept": "application/ld+json"}

AAT_OBJECT_NUMBER = "http://vocab.getty.edu/aat/300312355"
AAT_ENGLISH = "http://vocab.getty.edu/aat/300388277"

_CONCURRENCY = 8


def _as_list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _ids(items) -> set[str]:
    return {i.get("id") for i in _as_list(items) if isinstance(i, dict)}


def _title(art: dict) -> str | None:
    names = [n for n in _as_list(art.get("identified_by")) if n.get("type") == "Name"]
    for n in names:
        if AAT_ENGLISH in _ids(n.get("language")):
            return n.get("content")
    return names[0].get("content") if names else None


def _object_number(art: dict) -> str | None:
    for n in _as_list(art.get("identified_by")):
        if n.get("type") == "Identifier" and AAT_OBJECT_NUMBER in _ids(n.get("classified_as")):
            return n.get("content")
    return None


def _creator(art: dict) -> str | None:
    for ref in _as_list((art.get("produced_by") or {}).get("referred_to_by")):
        if ref.get("content"):
            return ref["content"]
    return None


def _web_link(art: dict) -> str | None:
    for sub in _as_list(art.get("subject_of")):
        for dig in _as_list(sub.get("digitally_carried_by")):
            if dig.get("format") == "text/html":
                for ap in _as_list(dig.get("access_point")):
                    if ap.get("id"):
                        return ap["id"]
    return None


async def _resolve(client: httpx.AsyncClient, oid: str) -> dict | None:
    r = await client.get(RESOLVE_URL.format(oid=oid), headers=HEADERS)
    if r.status_code != 200:
        return None
    return r.json()


async def _image_url(client: httpx.AsyncClient, art: dict) -> str | None:
    shows = _as_list(art.get("shows"))
    if not shows or not shows[0].get("id"):
        return None
    visual = await _resolve(client, shows[0]["id"].rsplit("/", 1)[-1])
    if not visual:
        return None
    shown_by = _as_list(visual.get("digitally_shown_by"))
    if not shown_by or not shown_by[0].get("id"):
        return None
    digital = await _resolve(client, shown_by[0]["id"].rsplit("/", 1)[-1])
    if not digital:
        return None
    for ap in _as_list(digital.get("access_point")):
        if ap.get("id"):
            return ap["id"]
    return None


async def _fetch_item(client: httpx.AsyncClient, sem: asyncio.Semaphore, oid: str) -> dict | None:
    async with sem:
        try:
            art = await _resolve(client, oid)
            if not art:
                return None
            url = await _image_url(client, art)
            if not url:
                return None
            # IIIF Image API URL — swap "max" for a width to get a thumbnail
            thumb = url.replace("/full/max/", "/full/400,/")
            return {
                "id": oid,
                "url": url,
                "thumb": thumb,
                "title": _title(art),
                "credit": _creator(art),
                "html": _web_link(art),
            }
        except httpx.HTTPError:
            return None


async def search(query: str, per_page: int = 20) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as c:
        # The new API has no free-text parameter; try the most useful fields
        # in turn until one matches.
        ids: list[str] = []
        for field in ("creator", "title", "description"):
            r = await c.get(SEARCH_URL, params={field: query, "imageAvailable": "true"})
            r.raise_for_status()
            items = _as_list(r.json().get("orderedItems"))
            ids = [i["id"].rsplit("/", 1)[-1] for i in items if i.get("id")][:per_page]
            if ids:
                break
        if not ids:
            return []
        sem = asyncio.Semaphore(_CONCURRENCY)
        results = await asyncio.gather(*(_fetch_item(c, sem, oid) for oid in ids))
    return [r for r in results if r]


async def get(object_id: str) -> dict | None:
    oid = object_id.rstrip("/").rsplit("/", 1)[-1]
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as c:
        try:
            art = await _resolve(c, oid)
            if not art:
                return None
            url = await _image_url(c, art)
            if not url:
                return None
        except httpx.HTTPError:
            return None
    return {
        "id": _object_number(art) or oid,
        "url": url,
        "title": _title(art),
        "credit": _creator(art),
        "html": _web_link(art),
    }
