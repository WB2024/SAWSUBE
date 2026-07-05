"""Pixabay source unit tests — mocked httpx + optional live integration test."""
from __future__ import annotations
import os
import pytest
from unittest.mock import patch

# ── helpers ────────────────────────────────────────────────────────────────

_FAKE_HIT = {
    "id": 195893,
    "pageURL": "https://pixabay.com/en/blossom-bloom-flower-195893/",
    "type": "photo",
    "tags": "blossom, bloom, flower",
    "previewURL": "https://cdn.pixabay.com/photo/2013/10/15/09/12/flower-195893_150.jpg",
    "previewWidth": 150,
    "previewHeight": 84,
    "webformatURL": "https://cdn.pixabay.com/photo/2013/10/15/09/12/flower-195893_640.jpg",
    "webformatWidth": 640,
    "webformatHeight": 360,
    "largeImageURL": "https://cdn.pixabay.com/photo/2013/10/15/09/12/flower-195893_1280.jpg",
    "imageWidth": 4000,
    "imageHeight": 2250,
    "imageSize": 4731420,
    "views": 7671,
    "downloads": 6439,
    "likes": 5,
    "comments": 2,
    "user_id": 48777,
    "user": "Josch13",
    "userImageURL": "https://cdn.pixabay.com/user/2013/11/05/02-10-23-764_250x250.jpg",
}


def _fake_client(response_json: dict, status_code: int = 200):
    class FakeResponse:
        def __init__(self):
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception(f"HTTP {self.status_code}")

        def json(self):
            return response_json

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return FakeResponse()

    return FakeClient


def _reload(monkeypatch, key: str = "testkey"):
    import importlib, backend.config as cfg_mod
    monkeypatch.setenv("PIXABAY_API_KEY", key)
    importlib.reload(cfg_mod)
    import backend.services.sources.pixabay as mod
    importlib.reload(mod)
    return mod


# ── unit tests ─────────────────────────────────────────────────────────────

async def test_search_empty_when_no_key(tmp_workdir, monkeypatch):
    mod = _reload(monkeypatch, key="")
    result = await mod.search("landscape")
    assert result == {"items": [], "next": None}


async def test_get_none_when_no_key(tmp_workdir, monkeypatch):
    mod = _reload(monkeypatch, key="")
    result = await mod.get("195893")
    assert result is None


async def test_search_returns_normalised_list(tmp_workdir, monkeypatch):
    mod = _reload(monkeypatch)
    payload = {"total": 1, "totalHits": 1, "hits": [_FAKE_HIT]}
    with patch("backend.services.sources.pixabay.httpx.AsyncClient", _fake_client(payload)):
        out = await mod.search("flower", per_page=1)

    results = out["items"]
    assert len(results) == 1
    assert out["next"] is None  # totalHits=1 already covered by page 1
    r = results[0]
    assert r["id"] == "195893"
    assert r["url"] == _FAKE_HIT["largeImageURL"]
    assert r["thumb"] == _FAKE_HIT["webformatURL"]
    assert r["title"] == "Blossom"           # first tag, title-cased
    assert r["credit"] == _FAKE_HIT["user"]
    assert "Josch13-48777" in r["credit_url"]
    assert r["html"] == _FAKE_HIT["pageURL"]


async def test_search_empty_hits(tmp_workdir, monkeypatch):
    mod = _reload(monkeypatch)
    payload = {"total": 0, "totalHits": 0, "hits": []}
    with patch("backend.services.sources.pixabay.httpx.AsyncClient", _fake_client(payload)):
        results = await mod.search("nothing here xyz")
    assert results == {"items": [], "next": None}


async def test_get_returns_normalised_dict(tmp_workdir, monkeypatch):
    mod = _reload(monkeypatch)
    payload = {"total": 1, "totalHits": 1, "hits": [_FAKE_HIT]}
    with patch("backend.services.sources.pixabay.httpx.AsyncClient", _fake_client(payload)):
        result = await mod.get("195893")
    assert result is not None
    assert result["id"] == "195893"
    assert result["url"] == _FAKE_HIT["largeImageURL"]


async def test_get_returns_none_on_empty_hits(tmp_workdir, monkeypatch):
    mod = _reload(monkeypatch)
    payload = {"total": 0, "totalHits": 0, "hits": []}
    with patch("backend.services.sources.pixabay.httpx.AsyncClient", _fake_client(payload)):
        result = await mod.get("999999")
    assert result is None


async def test_get_returns_none_on_http_error(tmp_workdir, monkeypatch):
    mod = _reload(monkeypatch)
    with patch("backend.services.sources.pixabay.httpx.AsyncClient", _fake_client({}, status_code=400)):
        result = await mod.get("123")
    assert result is None


async def test_per_page_clamped(tmp_workdir, monkeypatch):
    """per_page must be between 3 and 200."""
    mod = _reload(monkeypatch)
    captured: dict = {}

    class FakeResponse:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"hits": []}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None, **kw):
            captured.update(params or {})
            return FakeResponse()

    with patch("backend.services.sources.pixabay.httpx.AsyncClient", FakeClient):
        await mod.search("test", per_page=9999)
    assert captured.get("per_page") == 200

    with patch("backend.services.sources.pixabay.httpx.AsyncClient", FakeClient):
        await mod.search("test", per_page=1)
    assert captured.get("per_page") == 3


# ── live integration test (only when real key in env) ──────────────────────

@pytest.mark.skipif(
    not os.getenv("PIXABAY_API_KEY"),
    reason="PIXABAY_API_KEY not set — skipping live integration test",
)
async def test_live_pixabay_search(tmp_workdir, monkeypatch):
    """Hits real Pixabay API. Requires PIXABAY_API_KEY env var."""
    import importlib, backend.config as cfg_mod
    importlib.reload(cfg_mod)
    import backend.services.sources.pixabay as mod
    importlib.reload(mod)

    results = (await mod.search("mountain landscape", per_page=5))["items"]
    assert len(results) > 0
    r = results[0]
    for key in ("id", "url", "thumb", "title", "credit"):
        assert key in r, f"missing key: {key}"
    assert r["url"] and r["url"].startswith("https://")
    assert r["thumb"] and r["thumb"].startswith("https://")
