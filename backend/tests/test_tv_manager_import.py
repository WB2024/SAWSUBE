"""The TV library must import under its current package name (samsungframetv)."""
from __future__ import annotations
import pytest


def test_samsungframetv_is_detected(tmp_workdir):
    pytest.importorskip("samsungframetv")
    from backend.services import tv_manager

    assert tv_manager.HAS_LIB is True
    from samsungframetv.async_art import SamsungTVAsyncArt
    from samsungframetv.async_remote import SamsungTVWSAsyncRemote
    assert tv_manager.SamsungTVAsyncArt is SamsungTVAsyncArt
    assert tv_manager.SamsungTVWSAsyncRemote is SamsungTVWSAsyncRemote


def test_sqlalchemy_asyncio_extra_installed():
    # aiosqlite + AsyncSession need greenlet, which only comes with sqlalchemy[asyncio]
    pytest.importorskip("greenlet")
    import sqlalchemy.ext.asyncio  # noqa: F401
