"""TV router tests with mocked tv_manager."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch


async def test_list_empty(app_client):
    r = await app_client.get("/api/tvs")
    assert r.status_code == 200
    assert r.json() == []


async def test_add_tv_and_get(app_client):
    r = await app_client.post("/api/tvs", json={"name": "Living", "ip": "10.0.0.5", "port": 8002})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Living"
    assert body["ip"] == "10.0.0.5"

    r2 = await app_client.get(f"/api/tvs/{body['id']}")
    assert r2.status_code == 200
    assert r2.json()["id"] == body["id"]


async def test_get_unknown_tv_404(app_client):
    r = await app_client.get("/api/tvs/9999")
    assert r.status_code == 404


async def test_delete_tv(app_client):
    r = await app_client.post("/api/tvs", json={"name": "Bed", "ip": "10.0.0.6"})
    tv_id = r.json()["id"]
    with patch("backend.routers.tv.tv_manager.remove", new=AsyncMock(return_value=None)):
        r = await app_client.delete(f"/api/tvs/{tv_id}")
        assert r.status_code == 200
    r = await app_client.get(f"/api/tvs/{tv_id}")
    assert r.status_code == 404


async def test_status_offline_when_lib_missing(app_client):
    r = await app_client.post("/api/tvs", json={"name": "Office", "ip": "10.0.0.7"})
    tv_id = r.json()["id"]
    fake_status = {"online": False, "artmode": None, "current": None, "error": "lib missing"}
    with patch("backend.routers.tv.tv_manager.fetch_status",
               new=AsyncMock(return_value=fake_status)):
        r = await app_client.get(f"/api/tvs/{tv_id}/status")
        assert r.status_code == 200
        body = r.json()
        assert body["online"] is False
        assert body["error"] == "lib missing"


async def test_artmode_endpoints(app_client):
    r = await app_client.post("/api/tvs", json={"name": "Kitchen", "ip": "10.0.0.8"})
    tv_id = r.json()["id"]
    with patch("backend.routers.tv.tv_manager.set_artmode",
               new=AsyncMock(return_value=True)):
        r = await app_client.post(f"/api/tvs/{tv_id}/artmode/on")
        assert r.json()["ok"] is True
        r = await app_client.post(f"/api/tvs/{tv_id}/artmode/off")
        assert r.json()["ok"] is True


async def test_power_endpoints(app_client):
    r = await app_client.post("/api/tvs", json={"name": "Den", "ip": "10.0.0.9", "mac": "AA:BB:CC:DD:EE:FF"})
    tv_id = r.json()["id"]
    with patch("backend.routers.tv.tv_manager.power_on", new=AsyncMock(return_value=True)), \
         patch("backend.routers.tv.tv_manager.power_off", new=AsyncMock(return_value=True)):
        assert (await app_client.post(f"/api/tvs/{tv_id}/power/on")).json()["ok"] is True
        assert (await app_client.post(f"/api/tvs/{tv_id}/power/off")).json()["ok"] is True


async def test_discover_handles_failure(app_client):
    with patch("backend.routers.tv.discover_tvs", new=AsyncMock(side_effect=RuntimeError("net"))):
        r = await app_client.get("/api/tvs/discover")
        assert r.status_code == 503


async def test_discover_returns_results(app_client):
    payload = [{"ip": "10.0.0.1", "model": "QN65LS03"}]
    with patch("backend.routers.tv.discover_tvs", new=AsyncMock(return_value=payload)):
        r = await app_client.get("/api/tvs/discover")
        assert r.status_code == 200
        assert r.json() == payload


@pytest.mark.parametrize("token,paired", [
    (None, False), ("developer-mode\n", False), ("15614867", True),
])
async def test_status_paired_requires_real_token(app_client, token, paired):
    import os
    from pathlib import Path
    r = await app_client.post("/api/tvs", json={"name": "Frame", "ip": "10.0.0.8"})
    body = r.json()
    if token is not None:
        Path(os.environ["TOKEN_DIR"], f"tv_{body['id']}.token").write_text(token)
    offline = {"online": False, "artmode": None, "current": None}
    with patch("backend.routers.tv.tv_manager.fetch_status", new=AsyncMock(return_value=offline)):
        r = await app_client.get(f"/api/tvs/{body['id']}/status")
    assert r.json()["paired"] is paired
