"""Art channel lifecycle: errors close the websocket, calls are serialized."""
from __future__ import annotations
import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio


class FakeArt:
    instances: list["FakeArt"] = []

    def __init__(self, fail_on=(), delay=0.0):
        self.fail_on = set(fail_on)
        self.delay = delay
        self.closed = False
        self.in_flight = 0
        self.max_in_flight = 0
        FakeArt.instances.append(self)

    async def _op(self, name, result=None):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            if name in self.fail_on:
                raise ConnectionError(f"{name} failed")
            return result
        finally:
            self.in_flight -= 1

    async def close(self):
        self.closed = True

    async def get_artmode(self): return await self._op("get_artmode", "on")
    async def get_current(self): return await self._op("get_current", {"content_id": "MY_F0001"})
    async def available(self): return await self._op("available", [{"content_id": "MY_F0001"}])
    async def select_image(self, remote_id, show=True): return await self._op("select_image")
    async def delete_list(self, ids): return await self._op("delete_list")
    async def change_matte(self, remote_id, matte): return await self._op("change_matte")
    async def set_artmode(self, mode): return await self._op("set_artmode")
    async def get_matte_list(self): return await self._op("get_matte_list", ["none"])
    async def get_thumbnail(self, cid, as_bytes=True): return await self._op("get_thumbnail", b"jpg")
    async def upload(self, data, **kw): return await self._op("upload", "MY_F0002")
    async def get_device_info(self): return await self._op("get_device_info", {"model": "x"})


@pytest_asyncio.fixture()
async def env(tmp_workdir, monkeypatch):
    from backend.services import tv_manager as tm
    FakeArt.instances = []
    factory = {"make": lambda: FakeArt()}

    async def fake_new_art(self):
        return factory["make"]()

    monkeypatch.setattr(tm.TVConnection, "_new_art", fake_new_art)
    monkeypatch.setattr(tm, "HAS_LIB", True)
    m = tm.TVManager()
    tv = SimpleNamespace(id=1, ip="192.0.2.10", port=8002, mac=None, name="t", token_path=None)
    yield SimpleNamespace(tm=tm, m=m, tv=tv, factory=factory)
    await m.shutdown()


OPERATIONS = [
    ("select_image", lambda m, tv: m.select_image(tv, "MY_F0001"), False),
    ("delete_list", lambda m, tv: m.delete_image(tv, "MY_F0001"), False),
    ("available", lambda m, tv: m.list_images(tv), []),
    ("change_matte", lambda m, tv: m.set_matte(tv, "MY_F0001", "none"), False),
    ("set_artmode", lambda m, tv: m.set_artmode(tv, True), False),
    ("get_matte_list", lambda m, tv: m.list_mattes(tv), []),
    ("get_thumbnail", lambda m, tv: m.get_thumbnail(tv, "MY_F0001"), None),
    ("get_current", lambda m, tv: m.get_current(tv), None),
    ("get_device_info", lambda m, tv: m.device_info(tv), {}),
]


@pytest.mark.parametrize("op,call,default", OPERATIONS, ids=[o[0] for o in OPERATIONS])
async def test_failure_closes_art_and_next_call_reconnects(env, op, call, default):
    env.factory["make"] = lambda: FakeArt(fail_on={op})
    assert await call(env.m, env.tv) == default
    broken = FakeArt.instances[0]
    assert broken.closed, "the failed websocket must be closed, not just forgotten"
    conn = env.m.connections[env.tv.id]
    assert conn.art is None

    env.factory["make"] = lambda: FakeArt()
    assert await call(env.m, env.tv) != default
    assert len(FakeArt.instances) == 2


async def test_upload_failure_closes_art(env, make_jpeg):
    env.factory["make"] = lambda: FakeArt(fail_on={"upload"})
    assert await env.m.upload_image(env.tv, make_jpeg()) is None
    assert FakeArt.instances[0].closed


async def test_upload_missing_file_keeps_connection(env):
    await env.m.list_images(env.tv)
    assert await env.m.upload_image(env.tv, "/nonexistent.jpg") is None
    assert not FakeArt.instances[0].closed


async def test_fetch_status_failure_closes_art(env):
    from backend.database import init_db, SessionLocal
    from backend.models.tv import TV
    await init_db()
    async with SessionLocal() as s:
        row = TV(name="t", ip="192.0.2.10", port=8002)
        s.add(row)
        await s.commit()
        tv_id = row.id
    env.factory["make"] = lambda: FakeArt(fail_on={"get_artmode"})
    status = await env.m.fetch_status(tv_id)
    assert status["online"] is False
    assert FakeArt.instances[0].closed

    env.factory["make"] = lambda: FakeArt()
    status = await env.m.fetch_status(tv_id)
    assert status == {"online": True, "artmode": True, "current": "MY_F0001"}


async def test_concurrent_art_calls_are_serialized(env):
    env.factory["make"] = lambda: FakeArt(delay=0.02)
    await asyncio.gather(
        env.m.list_images(env.tv), env.m.set_matte(env.tv, "MY_F0001", "none"),
        env.m.get_current(env.tv), env.m.list_mattes(env.tv), env.m.device_info(env.tv),
    )
    assert len(FakeArt.instances) == 1, "a single art channel must be shared"
    assert FakeArt.instances[0].max_in_flight == 1


async def test_power_off_failure_drops_remote(env, monkeypatch):
    closed = []

    class FakeRemote:
        async def send_command(self, cmd): raise ConnectionError("gone")
        async def close(self): closed.append(True)

    async def fake_new_remote(self):
        return FakeRemote()

    monkeypatch.setattr(env.tm.TVConnection, "_new_remote", fake_new_remote)
    assert await env.m.power_off(env.tv) is False
    assert closed == [True]
    assert env.m.connections[env.tv.id].remote is None
