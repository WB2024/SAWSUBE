"""FrameArt handshake: the art channel must open whatever the startup event order.

Sequences are taken from a real QE32LS03C (2023 32" Frame) art channel.
"""
from __future__ import annotations
import asyncio
import json
import pytest

pytest.importorskip("samsungframetv")
from websockets.protocol import State  # noqa: E402

CONNECT = {"event": "ms.channel.connect", "data": {}}
READY = {"event": "ms.channel.ready", "data": {}}
CLIENT_CONNECT = {"event": "ms.channel.clientConnect", "data": {"attributes": {"name": "RnJhbWUgVFY="}}}
CLIENT_DISCONNECT = {"event": "ms.channel.clientDisconnect", "data": {}}


class FakeWebSocket:
    def __init__(self, messages):
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        for m in messages:
            self.queue.put_nowait(json.dumps(m))
        self.state = State.OPEN
        self.closed = False

    async def recv(self):
        return await self.queue.get()  # blocks forever once drained, like a silent TV

    async def close(self):
        self.closed = True
        self.state = State.CLOSED


@pytest.fixture()
def fake_tv(monkeypatch, tmp_workdir):
    """Return a factory that makes FrameArt talk to a FakeWebSocket."""
    from backend.services import tv_manager
    import samsungframetv.async_connection as conn_mod

    def _make(messages):
        ws = FakeWebSocket(messages)

        async def fake_connect(url, **kwargs):
            return ws

        monkeypatch.setattr(conn_mod, "connect", fake_connect)
        art = tv_manager.FrameArt(host="192.0.2.10", port=8002, timeout=0.5, name="test",
                                  token_file=str(tmp_workdir / "token"))
        return art, ws

    return _make


@pytest.mark.parametrize("sequence", [
    pytest.param([CONNECT, READY], id="library-order"),
    pytest.param([READY, CONNECT], id="ready-before-connect"),
    pytest.param([CLIENT_CONNECT, CONNECT, CLIENT_DISCONNECT, READY], id="ls03c-client-events"),
])
async def test_open_succeeds_for_real_world_orders(fake_tv, sequence):
    art, ws = fake_tv(sequence)
    connection = await art.open()
    assert connection is ws
    assert art._frame_ready is True
    assert not ws.closed


async def test_open_without_ready_fails_and_closes(fake_tv):
    from samsungframetv import exceptions
    art, ws = fake_tv([CLIENT_CONNECT, CONNECT, CLIENT_DISCONNECT])
    with pytest.raises(exceptions.ConnectionFailure, match="ms.channel.ready"):
        await art.open()
    assert ws.closed


async def test_open_unauthorized_is_not_swallowed(fake_tv):
    from samsungframetv import exceptions
    art, ws = fake_tv([CLIENT_CONNECT, {"event": "ms.channel.unauthorized", "data": {}}])
    with pytest.raises(exceptions.UnauthorizedError):
        await art.open()
    assert ws.closed
