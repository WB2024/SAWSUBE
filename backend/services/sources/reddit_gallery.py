from __future__ import annotations
import asyncio
import html
import json as _json
import logging
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from ...config import settings

log = logging.getLogger(__name__)

_last_call = 0.0
_lock = asyncio.Lock()
_SUB_RE = re.compile(r"^[A-Za-z0-9_]{1,50}$")
_SSL_CTX = ssl.create_default_context()


def _fetch_reddit_json(url: str, params: dict, user_agent: str) -> dict:
    """Synchronous urllib fetch — avoids httpx TLS fingerprint blocking by Reddit/Cloudflare."""
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full_url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, context=_SSL_CTX, timeout=15) as resp:
        return _json.loads(resp.read().decode())

# Reddit gallery posts store image metadata in media_metadata keyed by media_id.
# Each item has a "p" (preview) list and an "s" (source) dict with "u" (url).
# gallery_data.items gives the ordered list with media_id references.

_MIME_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",   # Reddit sometimes sends image/jpg (non-standard)
    "image/png": "png",
    "image/webp": "webp",
}


def _extract_gallery_images(post: dict) -> list[dict]:
    """Return list of {url, thumb, title, credit, html, subreddit, id} from a gallery post."""
    media_meta = post.get("media_metadata") or {}
    gallery_items = (post.get("gallery_data") or {}).get("items", [])
    title = post.get("title", "")
    author = post.get("author", "")
    permalink = "https://www.reddit.com" + post.get("permalink", "")
    subreddit = post.get("subreddit", "")
    post_id = post.get("id", "")

    out = []
    for idx, item in enumerate(gallery_items):
        media_id = item.get("media_id", "")
        meta = media_meta.get(media_id) or {}
        if meta.get("status") != "valid":
            continue
        mime = meta.get("m", "image/jpeg")
        if mime not in _MIME_EXT:
            continue  # skip gif / video

        source = meta.get("s") or {}
        raw_url = source.get("u") or source.get("gif") or ""
        if not raw_url:
            continue
        full_url = html.unescape(raw_url)

        # Thumbnail: use the largest preview that's ≤ 640px wide, falling back to source
        previews = sorted(meta.get("p") or [], key=lambda x: x.get("x", 0))
        thumb_url = full_url
        for p in previews:
            if p.get("x", 0) >= 320:
                thumb_url = html.unescape(p.get("u", full_url))
                break

        caption = item.get("caption") or title
        out.append({
            "id": f"{post_id}_{media_id}",
            "url": full_url,
            "thumb": thumb_url,
            "title": caption,
            "credit": author,
            "html": permalink,
            "subreddit": subreddit,
            "ext": _MIME_EXT[mime],
        })
    return out


async def fetch(sub: str, sort: str = "top", t: str = "week", limit: int = 20) -> list[dict]:
    """Fetch gallery posts from a subreddit. Returns flat list of individual images."""
    global _last_call
    if not _SUB_RE.match(sub or ""):
        return []
    if sort not in {"top", "hot", "new", "rising", "controversial"}:
        sort = "top"
    if t not in {"hour", "day", "week", "month", "year", "all"}:
        t = "week"
    # Fetch more posts than requested since many won't be galleries
    post_limit = min(max(int(limit), 1), 100)

    async with _lock:
        loop = asyncio.get_running_loop()
        delay = 2.0 - (loop.time() - _last_call)
        if delay > 0:
            await asyncio.sleep(delay)
        url = f"https://www.reddit.com/r/{sub}/{sort}.json"
        params = {"limit": post_limit, "t": t}
        user_agent = settings.REDDIT_USER_AGENT
        try:
            j = await loop.run_in_executor(
                None, _fetch_reddit_json, url, params, user_agent
            )
        except urllib.error.HTTPError as exc:
            log.warning("Reddit gallery fetch blocked (HTTP %s): %s", exc.code, url)
            return []
        except Exception as exc:
            log.warning("Reddit gallery fetch error: %s", exc)
            return []
        _last_call = loop.time()

    out: list[dict] = []
    for child in (j.get("data") or {}).get("children", []):
        d = child.get("data") or {}
        # Gallery posts have is_gallery=True and a media_metadata dict
        if not d.get("is_gallery") or not d.get("media_metadata"):
            continue
        out.extend(_extract_gallery_images(d))

    return out
