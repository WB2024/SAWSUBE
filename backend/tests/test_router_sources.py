"""Sources router tests."""
from __future__ import annotations
import os
from unittest.mock import AsyncMock, patch


async def test_add_folder_valid(app_client, tmp_path):
    p = tmp_path / "watch"
    p.mkdir()
    with patch("backend.routers.sources.watcher.add", lambda *a, **kw: None):
        r = await app_client.post("/api/sources/folders",
                                  json={"path": str(p), "is_active": True, "auto_display": False})
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == os.path.abspath(str(p))


async def test_add_folder_invalid(app_client):
    r = await app_client.post("/api/sources/folders",
                              json={"path": "/no/such/path/abc", "is_active": True, "auto_display": False})
    assert r.status_code == 400


async def test_list_folders_empty(app_client):
    r = await app_client.get("/api/sources/folders")
    assert r.status_code == 200
    assert r.json() == []


async def test_delete_folder_404(app_client):
    r = await app_client.delete("/api/sources/folders/9999")
    assert r.status_code == 404


async def test_unsplash_search_mocked(app_client):
    fake = {"items": [{"id": "x", "url": "https://example.com/x.jpg"}], "next": None}
    with patch("backend.routers.sources.settings.UNSPLASH_API_KEY", "testkey"), \
         patch("backend.routers.sources.unsplash.search",
               new=AsyncMock(return_value=fake)):
        r = await app_client.get("/api/sources/unsplash/search?q=mountain")
        assert r.json() == fake


async def test_unsplash_import_requires_id(app_client):
    r = await app_client.post("/api/sources/unsplash/import", json={})
    assert r.status_code == 400


async def test_nasa_apod_no_image(app_client):
    with patch("backend.routers.sources.nasa_apod.today",
               new=AsyncMock(return_value={"unsupported": True})):
        r = await app_client.post("/api/sources/nasa/apod/import")
        assert r.status_code == 400


async def test_reddit_fetch_mocked(app_client):
    with patch("backend.routers.sources.reddit.fetch",
               new=AsyncMock(return_value={"items": [{"id": "abc", "url": "https://i.redd.it/x.jpg"}], "next": None})):
        r = await app_client.get("/api/sources/reddit/fetch?sub=earthporn&sort=top&t=week")
        assert r.status_code == 200
        assert r.json()["items"][0]["id"] == "abc"


async def test_reddit_import_requires_url(app_client):
    r = await app_client.post("/api/sources/reddit/import", json={})
    assert r.status_code == 400
