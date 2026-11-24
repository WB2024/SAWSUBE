"""The Met source: only public-domain paintings with an image are offered."""
from __future__ import annotations
from unittest.mock import AsyncMock, patch

import httpx
import pytest

PAINTING = {
    "objectID": 437853, "isPublicDomain": True, "objectName": "Painting",
    "primaryImage": "https://images.metmuseum.org/CRDImages/ep/original/DT1.jpg",
    "primaryImageSmall": "https://images.metmuseum.org/CRDImages/ep/web-large/DT1.jpg",
    "title": "Whalers", "artistDisplayName": "Joseph Mallord William Turner",
    "objectDate": "ca. 1845", "objectURL": "https://www.metmuseum.org/art/collection/search/437853",
}


@pytest.mark.parametrize("override", [
    {"isPublicDomain": False},
    {"primaryImage": ""},
    {"objectName": "Print"},
])
def test_normalize_rejects_non_public_domain_or_imageless_or_non_paintings(tmp_workdir, override):
    from backend.services.sources import met
    assert met.normalize({**PAINTING, **override}) is None


def test_normalize_keeps_metadata(tmp_workdir):
    from backend.services.sources import met
    out = met.normalize(PAINTING)
    assert out["id"] == "437853"
    assert out["credit"] == "Joseph Mallord William Turner"
    assert out["thumb"].endswith("web-large/DT1.jpg")
    assert out["license"] == "CC0"


@pytest.fixture()
def met_api(monkeypatch, tmp_workdir):
    from backend.services.sources import met
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        if req.url.path.endswith("/v1.1/search"):
            return httpx.Response(200, json={"total": 3, "objectIDs": [1, 2, 3]})
        oid = int(req.url.path.rsplit("/", 1)[-1])
        if oid == 1:
            return httpx.Response(200, json={**PAINTING, "objectID": 1})
        if oid == 2:
            return httpx.Response(200, json={**PAINTING, "objectID": 2, "isPublicDomain": False})
        return httpx.Response(500)

    def client():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                 headers={"User-Agent": met._USER_AGENT})

    monkeypatch.setattr(met, "_client", client)
    return met, seen


async def test_search_uses_v1_1_and_filters_results(met_api):
    met, seen = met_api
    out = await met.search("turner")
    assert [o["id"] for o in out] == ["1"]  # 2 not public domain, 3 failed: skipped
    search = seen[0]
    assert search.url.path == "/public/collection/v1.1/search"
    assert search.url.params["q"] == "turner"
    assert search.url.params["medium"] == "Paintings"
    assert all("python-httpx" not in r.headers["user-agent"] for r in seen)


async def test_get_returns_none_for_unknown_object(met_api, monkeypatch):
    met, _ = met_api
    monkeypatch.setattr(met, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(404))))
    assert await met.get("999999") is None


# ── router ────────────────────────────────────────────────────────────────
async def test_search_endpoint(app_client):
    with patch("backend.routers.sources.met.search", new=AsyncMock(return_value=[{"id": "1"}])):
        r = await app_client.get("/api/sources/met/search?q=monet")
    assert r.status_code == 200 and r.json() == [{"id": "1"}]


async def test_search_endpoint_502_when_api_down(app_client):
    with patch("backend.routers.sources.met.search",
               new=AsyncMock(side_effect=httpx.ConnectError("down"))):
        r = await app_client.get("/api/sources/met/search?q=monet")
    assert r.status_code == 502


async def test_search_requires_query(app_client):
    assert (await app_client.get("/api/sources/met/search?q=")).status_code == 422


@pytest.mark.parametrize("payload", [{}, {"id": "abc"}, {"id": "1; DROP"}])
async def test_import_requires_numeric_id(app_client, payload):
    r = await app_client.post("/api/sources/met/import", json=payload)
    assert r.status_code == 400


async def test_import_404_when_not_public_domain(app_client):
    with patch("backend.routers.sources.met.get", new=AsyncMock(return_value=None)):
        r = await app_client.post("/api/sources/met/import", json={"id": "1"})
    assert r.status_code == 404


async def test_import_downloads_with_metadata(app_client):
    from backend.services.sources import met
    info = met.normalize(PAINTING)
    with patch("backend.routers.sources.met.get", new=AsyncMock(return_value=info)), \
         patch("backend.routers.sources.download_and_register",
               new=AsyncMock(return_value=None)) as dl:
        r = await app_client.post("/api/sources/met/import", json={"id": "437853"})
    assert r.status_code == 502  # download failed
    url, source, filename, meta = dl.await_args.args
    assert (url, source, filename) == (PAINTING["primaryImage"], "met", "met_437853.jpg")
    assert meta["credit"] == "Joseph Mallord William Turner" and meta["license"] == "CC0"
    from backend.services.sources.common import download_urllib
    assert dl.await_args.kwargs["downloader"] is download_urllib
