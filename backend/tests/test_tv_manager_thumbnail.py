"""tv_manager.get_thumbnail: one fetch at a time per TV, bounded, backs off with the art service."""
from __future__ import annotations
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock


def _manager_with_fake_art(tmp_workdir, art):
    from backend.services.tv_manager import TVManager, TVConnection
    tv = SimpleNamespace(id=1, ip="10.0.0.30", port=8002, mac=None, name="Frame", token_path=None)
    mgr = TVManager()
    conn = TVConnection(tv)
    conn._ensure_art = AsyncMock(return_value=art)  # type: ignore[method-assign]
    conn.art = art
    mgr.connections[tv.id] = conn  # pre-registered → get() won't start a poll loop
    return mgr, conn, tv


async def test_returns_bytes(tmp_workdir):
    art = SimpleNamespace(art_service_available=True, get_thumbnail=AsyncMock(return_value=b"jpg"))
    mgr, _, tv = _manager_with_fake_art(tmp_workdir, art)
    assert await mgr.get_thumbnail(tv, "MY_F0001") == b"jpg"
    art.get_thumbnail.assert_awaited_once_with("MY_F0001")


async def test_fetches_one_at_a_time(tmp_workdir):
    active = peak = 0

    async def fetch(_cid):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return b"jpg"

    art = SimpleNamespace(art_service_available=True, get_thumbnail=fetch)
    mgr, _, tv = _manager_with_fake_art(tmp_workdir, art)
    res = await asyncio.gather(*(mgr.get_thumbnail(tv, f"MY_F{i:04}") for i in range(6)))
    assert res == [b"jpg"] * 6
    assert peak == 1


async def test_skips_while_art_service_backing_off(tmp_workdir):
    art = SimpleNamespace(art_service_available=False, get_thumbnail=AsyncMock(return_value=b"jpg"))
    mgr, _, tv = _manager_with_fake_art(tmp_workdir, art)
    assert await mgr.get_thumbnail(tv, "MY_F0001") is None
    art.get_thumbnail.assert_not_awaited()


async def test_stalled_fetch_times_out_keeps_connection_and_releases(tmp_workdir):
    async def stall(_cid):
        await asyncio.sleep(10)

    art = SimpleNamespace(art_service_available=True, get_thumbnail=stall)
    mgr, conn, tv = _manager_with_fake_art(tmp_workdir, art)
    mgr.THUMB_FETCH_TIMEOUT = 0.05
    assert await mgr.get_thumbnail(tv, "MY_F0001") is None
    assert conn.art is art
    # semaphore released: the next fetch proceeds
    art.get_thumbnail = AsyncMock(return_value=b"jpg")
    assert await mgr.get_thumbnail(tv, "MY_F0002") == b"jpg"
