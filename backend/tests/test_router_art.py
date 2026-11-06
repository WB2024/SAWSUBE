"""Art router tests for the on-TV content listing endpoints (mocked tv_manager)."""
from __future__ import annotations
from unittest.mock import AsyncMock, patch


async def _setup(app_client) -> tuple[int, int]:
    """Create a TV plus one tracked image with remote_id MY_F0001. Returns (tv_id, tv_image_id)."""
    from backend.database import SessionLocal
    from backend.models.image import Image, TVImage

    tv_id = (await app_client.post("/api/tvs", json={"name": "Frame", "ip": "10.0.0.20"})).json()["id"]
    async with SessionLocal() as s:
        img = Image(local_path="/x.jpg", filename="x.jpg", file_hash="h1")
        s.add(img)
        await s.flush()
        ti = TVImage(tv_id=tv_id, image_id=img.id, remote_id="MY_F0001", is_on_tv=True)
        stale = TVImage(tv_id=tv_id, image_id=img.id, remote_id="MY_F0099", is_on_tv=True)
        s.add_all([ti, stale])
        await s.commit()
        return tv_id, ti.id


CONTENT = [
    {"content_id": "MY_F0001", "category_id": "MY-C0002", "matte_id": "none", "width": 3840, "height": 2160},
    {"content_id": "MY_F0002", "category_id": "MY-C0002", "matte_id": "modern_polar"},
]


async def test_available_marks_tracked(app_client):
    tv_id, ti_id = await _setup(app_client)
    with patch("backend.routers.art.tv_manager.list_images", new=AsyncMock(return_value=CONTENT)) as m:
        r = await app_client.get(f"/api/tvs/{tv_id}/art/available?category=MY-C0002")
    assert r.status_code == 200
    assert m.await_args.kwargs["category"] == "MY-C0002"
    body = {c["content_id"]: c for c in r.json()}
    assert body["MY_F0001"]["tv_image_id"] == ti_id
    assert body["MY_F0001"]["width"] == 3840
    assert body["MY_F0002"]["tv_image_id"] is None


async def test_available_tv_unreachable_502(app_client):
    tv_id, _ = await _setup(app_client)
    with patch("backend.routers.art.tv_manager.list_images", new=AsyncMock(return_value=None)):
        r = await app_client.get(f"/api/tvs/{tv_id}/art/available")
    assert r.status_code == 502


async def test_available_unknown_tv_404(app_client):
    r = await app_client.get("/api/tvs/999/art/available")
    assert r.status_code == 404


async def test_show_available(app_client):
    tv_id, _ = await _setup(app_client)
    with patch("backend.routers.art.tv_manager.select_image", new=AsyncMock(return_value=True)) as m:
        r = await app_client.post(f"/api/tvs/{tv_id}/art/available/MY_F0002/show")
    assert r.json()["ok"] is True
    assert m.await_args.args[1] == "MY_F0002"


async def test_available_ignores_removed_rows(app_client):
    """A removed row must not claim content whose id the TV has since reused."""
    from backend.database import SessionLocal
    from backend.models.image import TVImage
    tv_id, ti_id = await _setup(app_client)
    async with SessionLocal() as s:
        (await s.get(TVImage, ti_id)).is_on_tv = False
        await s.commit()
    with patch("backend.routers.art.tv_manager.list_images", new=AsyncMock(return_value=CONTENT)):
        r = await app_client.get(f"/api/tvs/{tv_id}/art/available")
    body = {c["content_id"]: c for c in r.json()}
    assert body["MY_F0001"]["tv_image_id"] is None
    assert body["MY_F0001"]["image_id"] is None


async def _on_tv(app_client, tv_id) -> set[str]:
    return {t["remote_id"] for t in (await app_client.get(f"/api/images/tv/{tv_id}")).json()}


async def test_delete_available_untracks(app_client):
    tv_id, _ = await _setup(app_client)
    after = [c for c in CONTENT if c["content_id"] != "MY_F0001"]
    with patch("backend.routers.art.tv_manager.delete_image", new=AsyncMock(return_value=True)), \
         patch("backend.routers.art.tv_manager.list_images", new=AsyncMock(return_value=after)):
        r = await app_client.delete(f"/api/tvs/{tv_id}/art/available/MY_F0001")
    assert r.json()["ok"] is True
    assert await _on_tv(app_client, tv_id) == {"MY_F0099"}


async def test_delete_available_not_confirmed_keeps_row(app_client):
    """TV didn't really delete (e.g. request timed out) → report failure, keep tracking."""
    tv_id, _ = await _setup(app_client)
    with patch("backend.routers.art.tv_manager.delete_image", new=AsyncMock(return_value=True)), \
         patch("backend.routers.art.tv_manager.list_images", new=AsyncMock(return_value=CONTENT)):
        r = await app_client.delete(f"/api/tvs/{tv_id}/art/available/MY_F0001")
    assert r.json()["ok"] is False
    assert await _on_tv(app_client, tv_id) == {"MY_F0001", "MY_F0099"}


async def test_delete_available_unconfirmable_502_keeps_row(app_client):
    tv_id, _ = await _setup(app_client)
    with patch("backend.routers.art.tv_manager.delete_image", new=AsyncMock(return_value=True)), \
         patch("backend.routers.art.tv_manager.list_images", new=AsyncMock(return_value=None)):
        r = await app_client.delete(f"/api/tvs/{tv_id}/art/available/MY_F0001")
    assert r.status_code == 502
    assert await _on_tv(app_client, tv_id) == {"MY_F0001", "MY_F0099"}


async def test_delete_available_tv_error(app_client):
    tv_id, _ = await _setup(app_client)
    lister = AsyncMock(return_value=[])
    with patch("backend.routers.art.tv_manager.delete_image", new=AsyncMock(return_value=False)), \
         patch("backend.routers.art.tv_manager.list_images", new=lister):
        r = await app_client.delete(f"/api/tvs/{tv_id}/art/available/MY_F0001")
    assert r.json()["ok"] is False
    lister.assert_not_awaited()
    assert await _on_tv(app_client, tv_id) == {"MY_F0001", "MY_F0099"}


async def test_tv_thumbnail_cache_header(app_client):
    tv_id, _ = await _setup(app_client)
    with patch("backend.routers.images.tv_manager.get_thumbnail", new=AsyncMock(return_value=b"\xff\xd8jpg")):
        r = await app_client.get(f"/api/images/tv/{tv_id}/thumbnail/MY_F0001")
    assert r.status_code == 200
    assert "max-age" in r.headers["cache-control"]
    with patch("backend.routers.images.tv_manager.get_thumbnail", new=AsyncMock(return_value=None)):
        r = await app_client.get(f"/api/images/tv/{tv_id}/thumbnail/MY_F0001")
    assert r.status_code == 404
    assert "max-age" not in r.headers.get("cache-control", "")


async def test_reconcile_marks_stale(app_client):
    tv_id, _ = await _setup(app_client)
    with patch("backend.routers.art.tv_manager.list_images", new=AsyncMock(return_value=CONTENT)):
        r = await app_client.post(f"/api/tvs/{tv_id}/art/reconcile")
    assert r.status_code == 200
    assert r.json()["marked_removed"] == 1
    remaining = {t["remote_id"] for t in (await app_client.get(f"/api/images/tv/{tv_id}")).json()}
    assert remaining == {"MY_F0001"}


async def test_reconcile_tv_unreachable_keeps_rows(app_client):
    tv_id, _ = await _setup(app_client)
    with patch("backend.routers.art.tv_manager.list_images", new=AsyncMock(return_value=None)):
        r = await app_client.post(f"/api/tvs/{tv_id}/art/reconcile")
    assert r.status_code == 502
    assert len((await app_client.get(f"/api/images/tv/{tv_id}")).json()) == 2
