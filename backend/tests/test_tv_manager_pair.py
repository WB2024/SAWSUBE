"""Pairing must only report success once the TV has issued a real token."""
from __future__ import annotations
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio


@pytest_asyncio.fixture()
async def manager(tmp_workdir):
    from backend.services.tv_manager import TVManager
    m = TVManager()
    yield m
    await m.shutdown()


def _tv(tmp_workdir, tv_id=1):
    return SimpleNamespace(id=tv_id, ip="192.0.2.10", port=8002, mac=None, name="Test",
                           token_path=str(tmp_workdir / "data" / "tokens" / f"tv_{tv_id}.token"))


def _fake_remote(monkeypatch, behaviour):
    from backend.services import tv_manager as tm
    calls = []

    async def fake_ensure_remote(self):
        calls.append(Path(self.token_file).read_text() if Path(self.token_file).exists() else None)
        await behaviour(self)
        self.remote = object()
        return self.remote

    monkeypatch.setattr(tm.TVConnection, "_ensure_remote", fake_ensure_remote)
    monkeypatch.setattr(tm, "HAS_LIB", True)
    return calls


async def test_pair_true_when_tv_issues_token(manager, tmp_workdir, monkeypatch):
    async def issue_token(conn):
        Path(conn.token_file).write_text("15614867")
    _fake_remote(monkeypatch, issue_token)
    tv = _tv(tmp_workdir)
    assert await manager.pair(tv) is True


async def test_pair_false_without_token_and_writes_no_placeholder(manager, tmp_workdir, monkeypatch):
    async def no_token(conn):
        pass
    _fake_remote(monkeypatch, no_token)
    tv = _tv(tmp_workdir)
    assert await manager.pair(tv) is False
    assert not Path(tv.token_path).exists()


async def test_pair_false_on_timeout(manager, tmp_workdir, monkeypatch):
    async def never_answers(conn):
        await asyncio.sleep(10)
    _fake_remote(monkeypatch, never_answers)
    monkeypatch.setattr(type(manager), "PAIR_TIMEOUT_SECS", 0.05)
    assert await manager.pair(_tv(tmp_workdir)) is False


async def test_pair_drops_legacy_placeholder_before_connecting(manager, tmp_workdir, monkeypatch):
    async def issue_token(conn):
        Path(conn.token_file).write_text("15614867")
    calls = _fake_remote(monkeypatch, issue_token)
    tv = _tv(tmp_workdir)
    Path(tv.token_path).write_text("developer-mode\n")
    assert await manager.pair(tv) is True
    assert calls == [None]  # the placeholder was never offered to the TV as a token
    assert Path(tv.token_path).read_text() == "15614867"


@pytest.mark.parametrize("content,expected", [
    (None, False), ("", False), ("developer-mode\n", False), ("15614867", True),
])
def test_has_real_token(tmp_path, tmp_workdir, content, expected):
    from backend.services.tv_manager import has_real_token
    f = tmp_path / "t.token"
    if content is not None:
        f.write_text(content)
    assert has_real_token(str(f)) is expected
