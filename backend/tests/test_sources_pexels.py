"""Pexels source unit tests — mocked httpx + optional live integration test."""
from __future__ import annotations
import os
import pytest
from unittest.mock import patch, MagicMock

# ── helpers ────────────────────────────────────────────────────────────────

_FAKE_PHOTO = {
    "id": 123456,
    "width": 3840,
    "height": 2160,
    "url": "https://www.pexels.com/photo/test-123456/",
    "photographer": "Test Photographer",
    "photographer_url": "https://www.pexels.com/@test",
    "photographer_id": 1,
    "avg_color": "#AABBCC",
    "src": {
        "original": "https://images.pexels.com/photos/123456/test.jpg",
        "large2x": "https://images.pexels.com/photos/123456/test.jpg?dpr=2",
        "large": "https://images.pexels.com/photos/123456/test.jpg?large",
        "medium": "https://images.pexels.com/photos/123456/test.jpg?medium",
        "small": "https://images.pexels.com/photos/123456/test.jpg?small",
        "portrait": "https://images.pexels.com/photos/123456/test.jpg?portrait",
        "landscape": "https://images.pexels.com/photos/123456/test.jpg?landscape",
        "tiny": "https://images.pexels.com/photos/123456/test.jpg?tiny",
    },
    "liked": False,
    "alt": "A beautiful landscape",
}


def _fake_client(response_json: dict):
    """Return a context-manager-compatible mock AsyncClient."""
    class FakeResponse:
        status_code = 200

        def raise_for_status(self): pass

        def json(self):
            return response_json

    class FakeClient:
        def __init__(self, *a, **kw): pass

        async def __aenter__(self): return self

        async def __aexit__(self, *a): pass

        async def get(self, url, **kw):
            return FakeResponse()

    return FakeClient


# ── unit tests ─────────────────────────────────────────────────────────────

async def test_search_empty_when_no_api_key(tmp_workdir, monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "")
    import importlib, backend.services.sources.pexels as mod
    importlib.reload(mod)
    # reload settings so it picks up blank key
    import backend.config as cfg_mod
    importlib.reload(cfg_mod)
    importlib.reload(mod)
    result = await mod.search("landscape")
    assert result == {"items": [], "next": None}


async def test_get_none_when_no_api_key(tmp_workdir, monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "")
    import importlib, backend.services.sources.pexels as mod
    import backend.config as cfg_mod
    importlib.reload(cfg_mod)
    importlib.reload(mod)
    result = await mod.get("123456")
    assert result is None


async def test_search_returns_normalised_list(tmp_workdir, monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "testkey")
    import importlib, backend.config as cfg_mod
    importlib.reload(cfg_mod)
    import backend.services.sources.pexels as mod
    importlib.reload(mod)

    payload = {"photos": [_FAKE_PHOTO], "total_results": 1, "page": 1, "per_page": 1}
    with patch("backend.services.sources.pexels.httpx.AsyncClient", _fake_client(payload)):
        out = await mod.search("landscape", per_page=1)

    results = out["items"]
    assert len(results) == 1
    assert out["next"] is None  # no next_page in payload
    r = results[0]
    assert r["id"] == "123456"
    assert r["url"] == _FAKE_PHOTO["src"]["original"]
    assert r["thumb"] == _FAKE_PHOTO["src"]["medium"]
    assert r["title"] == _FAKE_PHOTO["alt"]
    assert r["credit"] == _FAKE_PHOTO["photographer"]
    assert r["credit_url"] == _FAKE_PHOTO["photographer_url"]
    assert r["html"] == _FAKE_PHOTO["url"]


async def test_search_empty_photos_key(tmp_workdir, monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "testkey")
    import importlib, backend.config as cfg_mod
    importlib.reload(cfg_mod)
    import backend.services.sources.pexels as mod
    importlib.reload(mod)

    payload = {"photos": [], "total_results": 0, "page": 1, "per_page": 1}
    with patch("backend.services.sources.pexels.httpx.AsyncClient", _fake_client(payload)):
        results = await mod.search("nothing")
    assert results == {"items": [], "next": None}


async def test_get_returns_normalised_dict(tmp_workdir, monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "testkey")
    import importlib, backend.config as cfg_mod
    importlib.reload(cfg_mod)
    import backend.services.sources.pexels as mod
    importlib.reload(mod)

    with patch("backend.services.sources.pexels.httpx.AsyncClient", _fake_client(_FAKE_PHOTO)):
        result = await mod.get("123456")

    assert result is not None
    assert result["id"] == "123456"
    assert result["url"] == _FAKE_PHOTO["src"]["original"]
    assert result["thumb"] == _FAKE_PHOTO["src"]["medium"]


async def test_get_returns_none_on_404(tmp_workdir, monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "testkey")
    import importlib, backend.config as cfg_mod
    importlib.reload(cfg_mod)
    import backend.services.sources.pexels as mod
    importlib.reload(mod)

    class FakeResponse404:
        status_code = 404

    class FakeClient404:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return FakeResponse404()

    with patch("backend.services.sources.pexels.httpx.AsyncClient", FakeClient404):
        result = await mod.get("999999")
    assert result is None


async def test_per_page_clamped_to_80(tmp_workdir, monkeypatch):
    """per_page > 80 must be clamped — Pexels rejects > 80."""
    monkeypatch.setenv("PEXELS_API_KEY", "testkey")
    import importlib, backend.config as cfg_mod
    importlib.reload(cfg_mod)
    import backend.services.sources.pexels as mod
    importlib.reload(mod)

    captured_params = {}

    class FakeResponse:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"photos": []}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None, **kw):
            captured_params.update(params or {})
            return FakeResponse()

    with patch("backend.services.sources.pexels.httpx.AsyncClient", FakeClient):
        await mod.search("test", per_page=200)

    assert captured_params.get("per_page") == 80


# ── router integration test ────────────────────────────────────────────────

async def test_router_pexels_search_mocked(tmp_workdir, monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "testkey")
    import importlib, backend.config as cfg_mod
    importlib.reload(cfg_mod)

    mock_results = {"items": [{"id": "1", "url": "http://example.com/img.jpg", "thumb": "http://example.com/t.jpg",
                     "title": "Test", "credit": "Tester", "credit_url": None, "html": "http://pexels.com/photo/1",
                     "width": 1920, "height": 1080}], "next": None}
    with patch("backend.services.sources.pexels.search", return_value=mock_results):
        import backend.main as main_mod
        importlib.reload(main_mod)
        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as c:
            r = await c.get("/api/sources/pexels/search?q=landscape")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["items"], list)


# ── live integration test (only runs when real key in env) ─────────────────

@pytest.mark.skipif(
    not os.getenv("PEXELS_API_KEY"),
    reason="PEXELS_API_KEY not set — skipping live integration test",
)
async def test_live_pexels_search(tmp_workdir, monkeypatch):
    """Hits real Pexels API. Requires PEXELS_API_KEY env var."""
    import importlib, backend.config as cfg_mod
    importlib.reload(cfg_mod)
    import backend.services.sources.pexels as mod
    importlib.reload(mod)

    results = (await mod.search("mountain landscape", per_page=5))["items"]
    assert len(results) > 0
    r = results[0]
    for key in ("id", "url", "thumb", "title", "credit"):
        assert key in r, f"missing key: {key}"
    assert r["url"].startswith("https://")
    assert r["thumb"].startswith("https://")
