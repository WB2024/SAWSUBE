"""Config and database init tests."""
from __future__ import annotations


def test_settings_defaults(tmp_workdir):
    from backend.config import settings
    assert settings.DB_PATH.endswith("sawsube.db")
    assert "sawsube" in settings.REDDIT_USER_AGENT.lower()


async def test_init_db_idempotent(tmp_workdir):
    from backend.database import init_db
    await init_db()
    await init_db()  # second call must not raise


async def test_foreign_keys_enabled(tmp_workdir):
    """SQLite FK pragma must be on in every session."""
    from backend.database import init_db, SessionLocal
    from sqlalchemy import text
    await init_db()
    async with SessionLocal() as s:
        r = await s.execute(text("PRAGMA foreign_keys"))
        assert r.scalar_one() == 1


async def test_get_session_yields_session(tmp_workdir):
    from backend.database import init_db, get_session
    from sqlalchemy.ext.asyncio import AsyncSession
    await init_db()
    gen = get_session()
    s = await gen.__anext__()
    try:
        assert isinstance(s, AsyncSession)
    finally:
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass


def test_tv_log_level_default_is_info(tmp_workdir, monkeypatch):
    import logging
    monkeypatch.delenv("TV_LOG_LEVEL", raising=False)
    import backend.main  # noqa: F401  (configures logging on import)
    for name in ("backend.services.tv_manager", "samsungframetv", "samsungframetv.async_art"):
        assert logging.getLogger(name).getEffectiveLevel() == logging.INFO


def test_tv_log_level_from_env(tmp_workdir, monkeypatch):
    import logging
    monkeypatch.setenv("TV_LOG_LEVEL", "debug")
    import backend.main  # noqa: F401
    assert logging.getLogger("samsungframetv.async_art").getEffectiveLevel() == logging.DEBUG
    assert logging.getLogger("backend.services.tv_manager").getEffectiveLevel() == logging.DEBUG


def test_tv_log_level_invalid_falls_back_to_info(tmp_workdir):
    import logging
    from backend.main import configure_tv_logging
    configure_tv_logging("chatty")
    assert logging.getLogger("samsungframetv").level == logging.INFO
