"""The SPA catch-all route must never serve files outside FRONTEND_DIST."""
from __future__ import annotations
import pytest
import pytest_asyncio


@pytest_asyncio.fixture()
async def spa_client(tmp_workdir, monkeypatch):
    dist = tmp_workdir / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>INDEX</html>")
    (dist / "logo.svg").write_text("<svg>LOGO</svg>")
    (tmp_workdir / "secret.txt").write_text("TOP-SECRET")  # sibling of dist
    monkeypatch.setenv("FRONTEND_DIST", str(dist))
    from httpx import AsyncClient, ASGITransport
    from backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_serves_existing_file(spa_client):
    r = await spa_client.get("/logo.svg")
    assert r.status_code == 200
    assert "LOGO" in r.text


async def test_unknown_route_falls_back_to_index(spa_client):
    r = await spa_client.get("/library")
    assert "INDEX" in r.text


@pytest.mark.parametrize("path", [
    "/..%2fsecret.txt",
    "/%2e%2e/secret.txt",
    "/%2e%2e%2fsecret.txt",
    "/assets%2f..%2f..%2fsecret.txt",
])
async def test_traversal_never_leaks_files(spa_client, path):
    r = await spa_client.get(path)
    assert "TOP-SECRET" not in r.text


async def test_absolute_path_not_served(spa_client, tmp_workdir):
    r = await spa_client.get("/" + str(tmp_workdir / "secret.txt").lstrip("/").replace("/", "%2f"))
    assert "TOP-SECRET" not in r.text
