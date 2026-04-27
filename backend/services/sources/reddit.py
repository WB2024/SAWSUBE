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


async def fetch(sub: str, sort: str = "top", t: str = "week", limit: int = 20) -> list[dict]:
    global _last_call
    if not _SUB_RE.match(sub or ""):
        return []
    if sort not in {"top", "hot", "new", "rising", "controversial"}:
        sort = "top"
    if t not in {"hour", "day", "week", "month", "year", "all"}:
        t = "week"
    limit = max(1, min(int(limit), 100))
    async with _lock:
        loop = asyncio.get_running_loop()
        delay = 2.0 - (loop.time() - _last_call)
        if delay > 0:
            await asyncio.sleep(delay)
        url = f"https://www.reddit.com/r/{sub}/{sort}.json"
        params = {"limit": limit, "t": t}
        user_agent = settings.REDDIT_USER_AGENT
        try:
            j = await loop.run_in_executor(
                None, _fetch_reddit_json, url, params, user_agent
            )
        except urllib.error.HTTPError as exc:
            log.warning("Reddit fetch blocked (HTTP %s): %s", exc.code, url)
            return []
        except Exception as exc:
            log.warning("Reddit fetch error: %s", exc)
            return []
        _last_call = loop.time()
    out = []
    for child in (j.get("data") or {}).get("children", []):
        d = child.get("data") or {}
        if d.get("post_hint") != "image":
            continue
        url = html.unescape(d.get("url_overridden_by_dest") or d.get("url") or "")
        thumb = d.get("thumbnail") if str(d.get("thumbnail", "")).startswith("http") else url
        thumb = html.unescape(thumb or url)
        out.append({
            "id": d.get("id"),
            "url": url,
            "thumb": thumb,
            "title": d.get("title"),
            "credit": d.get("author"),
            "html": "https://www.reddit.com" + d.get("permalink", ""),
            "subreddit": d.get("subreddit"),
        })
    return out
