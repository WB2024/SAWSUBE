from __future__ import annotations
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from sqlalchemy import select
from ..config import settings
from ..database import SessionLocal
from ..models.tv import TV
from .ws_manager import ws_manager

log = logging.getLogger(__name__)

# samsungframetv (NickWaterton fork, formerly published as samsungtvws) optional
# import — guarded so app still boots even if user hasn't installed deps yet.
try:
    from samsungframetv.async_art import SamsungTVAsyncArt
    from samsungframetv.async_remote import SamsungTVWSAsyncRemote
    from samsungframetv.async_connection import SamsungTVWSAsyncConnection
    from samsungframetv import exceptions as tv_exceptions, helper as tv_helper
    from samsungframetv.event import IGNORE_EVENTS_AT_STARTUP

    MS_CHANNEL_READY = "ms.channel.ready"
    # Events the TV's own art-app client can interleave with the handshake.
    _ART_STARTUP_NOISE = frozenset({
        MS_CHANNEL_READY, "ms.channel.clientConnect", "ms.channel.clientDisconnect",
    })

    class FrameArt(SamsungTVAsyncArt):
        """Art channel that does not depend on the exact startup event order.

        The library expects ``ms.channel.connect`` as the first relevant event
        and ``ms.channel.ready`` as the very next message. A 2023 32" Frame
        (QE32LS03C) instead sends e.g. ``ms.channel.clientConnect`` (its own
        art-app client) before ``connect`` and ``clientDisconnect`` before
        ``ready``, which makes the base ``open()`` fail or time out.

        Skip those interleaved events, remember ``ready`` whenever it is seen
        (even before ``connect``) and only wait for it if it has not arrived yet.
        """

        def _websocket_event(self, event, response):
            if event == MS_CHANNEL_READY:
                self._frame_ready = True
            super()._websocket_event(event, response)

        async def _wait_for_connect_event(self, connection):
            while True:
                response = tv_helper.process_api_response(await connection.recv())
                event = response.get("event", "*")
                self._websocket_event(event, response)
                if event not in IGNORE_EVENTS_AT_STARTUP and event not in _ART_STARTUP_NOISE:
                    return response

        async def open(self):
            if self.is_alive():
                return self.connection
            self._frame_ready = False
            # Skip SamsungTVAsyncArt.open: it insists that the next message is ready.
            await SamsungTVWSAsyncConnection.open(self)

            async def _wait_ready():
                while not self._frame_ready:
                    response = tv_helper.process_api_response(await self.connection.recv())
                    self._websocket_event(response.get("event", "*"), response)

            if not self._frame_ready:
                try:
                    await asyncio.wait_for(_wait_ready(), self.timeout or 10)
                except asyncio.TimeoutError:
                    await self.close()
                    raise tv_exceptions.ConnectionFailure(
                        f"{self.host} art channel did not send {MS_CHANNEL_READY}"
                    ) from None
                except Exception:
                    await self.close()
                    raise
            return self.connection

    HAS_LIB = True
except Exception as e:  # pragma: no cover
    log.warning("samsungframetv not available: %s", e)
    SamsungTVAsyncArt = None  # type: ignore
    SamsungTVWSAsyncRemote = None  # type: ignore
    FrameArt = None  # type: ignore
    HAS_LIB = False

try:
    from wakeonlan import send_magic_packet
    HAS_WOL = True
except Exception:
    send_magic_packet = None  # type: ignore
    HAS_WOL = False


def token_path_for(tv: TV) -> str:
    return tv.token_path or os.path.join(settings.TOKEN_DIR, f"tv_{tv.id}.token")


# Older versions wrote this placeholder when a TV connected without issuing a
# token. It is not a token: sending it back makes the TV refuse or re-prompt.
LEGACY_PLACEHOLDER_TOKEN = "developer-mode"


def has_real_token(token_file: str) -> bool:
    try:
        token = Path(token_file).read_text().strip()
    except OSError:
        return False
    return bool(token) and token != LEGACY_PLACEHOLDER_TOKEN


def remove_legacy_placeholder_token(token_file: str) -> None:
    try:
        if Path(token_file).read_text().strip() == LEGACY_PLACEHOLDER_TOKEN:
            os.remove(token_file)
            log.info("removed legacy placeholder token %s", token_file)
    except OSError:
        pass


_INT_SETTINGS = frozenset({"brightness", "color_temp", "motion_sensitivity"})


def normalize_art_setting(key: str, value: Any) -> Any:
    """Turn raw art-channel setting replies into plain values for the API.

    Newer firmware answers ``{"item": "brightness", "value": "5", ...}`` rather
    than a bare value, and numbers arrive as strings. The slideshow status is a
    structured dict and is passed through unchanged.
    """
    if key == "slideshow":
        return value
    if isinstance(value, dict) and "value" in value:
        value = value["value"]
    if value is None:
        return None
    if key in _INT_SETTINGS:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if key == "brightness_sensor":
        return value is True or str(value).lower() in ("on", "true", "1")
    return value


def normalize_matte_list(res: Any) -> list[str]:
    """Return unique matte type names from any get_matte_list() reply shape.

    The library may return a list of names, a list of ``{"matte_type": ...}``
    dicts, or a dict wrapping that list.
    """
    if isinstance(res, dict):
        res = res.get("matte_types", res.get("matte_type_list", []))
    if not isinstance(res, list):
        return []
    names = [m if isinstance(m, str) else m.get("matte_type")
             for m in res if isinstance(m, (str, dict))]
    return list(dict.fromkeys(m for m in names if isinstance(m, str) and m))


class TVConnection:
    """One TV: lazily opened art/remote channels shared by all callers.

    Every art-channel operation goes through :meth:`art_session`, which holds
    ``lock`` for the whole request/response exchange (the art channel cannot
    multiplex concurrent requests reliably) and closes the channel on error, so
    a broken websocket and its listener task are never leaked.
    """

    def __init__(self, tv: TV) -> None:
        self.tv_id = tv.id
        self.ip = tv.ip
        self.port = tv.port
        self.mac = tv.mac
        self.name = tv.name
        self.token_file = token_path_for(tv)
        self.lock = asyncio.Lock()
        self.art: Optional[Any] = None
        self.remote: Optional[Any] = None
        self.last_status: dict[str, Any] = {"online": False, "artmode": None, "current": None}
        self._closed = False

    # ── channel factories (patched in tests) ─────────────────────────────────
    async def _new_art(self) -> Any:
        art = FrameArt(host=self.ip, port=self.port, token_file=self.token_file,
                       name=self.name or "SAWSUBE")
        await art.start_listening()
        return art

    async def _new_remote(self) -> Any:
        remote = SamsungTVWSAsyncRemote(host=self.ip, port=self.port, token_file=self.token_file,
                                        name=self.name or "SAWSUBE")
        await remote.start_listening()
        return remote

    # ── lock held by caller ──────────────────────────────────────────────────
    async def _ensure_art_locked(self) -> Any:
        if not HAS_LIB:
            raise RuntimeError("samsungframetv library not installed")
        if self.art is None:
            self.art = await self._new_art()
        return self.art

    async def _drop_art_locked(self) -> None:
        art, self.art = self.art, None
        if art is not None:
            try:
                await art.close()
            except Exception as e:
                log.debug("TV %s: closing art channel failed: %s", self.tv_id, e)

    async def _drop_remote_locked(self) -> None:
        remote, self.remote = self.remote, None
        if remote is not None:
            try:
                await remote.close()
            except Exception as e:
                log.debug("TV %s: closing remote channel failed: %s", self.tv_id, e)

    # ── public API ───────────────────────────────────────────────────────────
    @asynccontextmanager
    async def art_session(self):
        """Yield a connected art channel with the connection lock held.

        Any exception closes and drops the channel (the next call reconnects)
        and is re-raised to the caller."""
        async with self.lock:
            try:
                yield await self._ensure_art_locked()
            except Exception:
                await self._drop_art_locked()
                raise

    async def _ensure_art(self) -> Any:
        async with self.lock:
            return await self._ensure_art_locked()

    async def _ensure_remote(self) -> Any:
        if not HAS_LIB:
            raise RuntimeError("samsungframetv library not installed")
        async with self.lock:
            if self.remote is None:
                self.remote = await self._new_remote()
            return self.remote

    async def drop_remote(self) -> None:
        async with self.lock:
            await self._drop_remote_locked()

    async def reset_connection(self) -> None:
        """Close art/remote and clear handles — lock-safe relative to the poll loop."""
        async with self.lock:
            await self._drop_art_locked()
            await self._drop_remote_locked()

    async def close(self) -> None:
        self._closed = True
        await self.reset_connection()


class TVManager:
    PAIR_TIMEOUT_SECS = 45.0  # time for the user to press Allow on the TV

    def __init__(self) -> None:
        self.connections: dict[int, TVConnection] = {}
        self._poll_tasks: dict[int, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def get(self, tv: TV) -> TVConnection:
        async with self._lock:
            conn = self.connections.get(tv.id)
            if conn is None:
                conn = TVConnection(tv)
                self.connections[tv.id] = conn
                self._poll_tasks[tv.id] = asyncio.create_task(self._poll_loop(tv.id))
            else:
                # refresh basic fields in case TV row changed
                conn.ip = tv.ip
                conn.port = tv.port
                conn.mac = tv.mac
                conn.name = tv.name
            return conn

    async def remove(self, tv_id: int) -> None:
        async with self._lock:
            conn = self.connections.pop(tv_id, None)
            task = self._poll_tasks.pop(tv_id, None)
        if task:
            task.cancel()
        if conn:
            await conn.close()

    async def shutdown(self) -> None:
        for t in list(self._poll_tasks.values()):
            t.cancel()
        for c in list(self.connections.values()):
            await c.close()
        self.connections.clear()
        self._poll_tasks.clear()

    async def _poll_loop(self, tv_id: int) -> None:
        backoff = 5
        while True:
            try:
                await asyncio.sleep(settings.POLL_INTERVAL_SECS)
                conn = self.connections.get(tv_id)
                if conn is None or conn._closed:
                    return
                status = await self.fetch_status(tv_id)
                # Only broadcast when meaningful keys differ (ignore transient 'error' string)
                keys = ("online", "artmode", "current")
                changed = any(status.get(k) != conn.last_status.get(k) for k in keys)
                if changed:
                    conn.last_status = status
                    await ws_manager.broadcast({"type": "tv_status", "tv_id": tv_id, "payload": status})
                backoff = 5
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.debug("poll err tv %s: %s", tv_id, e)
                await asyncio.sleep(min(backoff, 60))
                backoff = min(backoff * 2, 60)

    async def fetch_status(self, tv_id: int) -> dict[str, Any]:
        async with SessionLocal() as s:
            tv = await s.get(TV, tv_id)
            if not tv:
                return {"online": False, "artmode": None, "current": None}
            conn = await self.get(tv)
            try:
                async with conn.art_session() as art:
                    artmode = await art.get_artmode()
                    current = None
                    try:
                        cur = await art.get_current()
                        current = cur.get("content_id") if isinstance(cur, dict) else None
                    except Exception:
                        pass
            except Exception as e:
                log.warning("fetch_status tv %s failed, resetting connection: %s", tv_id, e, exc_info=True)
                return {"online": False, "artmode": None, "current": None, "error": str(e)}
            tv.last_seen = datetime.utcnow()
            await s.commit()
            return {"online": True, "artmode": (artmode == "on" or artmode is True),
                    "current": current}

    # ── High-level operations ────────────────────────────────────────────────
    async def pair(self, tv: TV) -> bool:
        """Open the remote channel to trigger the Allow/Deny prompt on the TV and
        wait for the token it issues (up to ~45 s, time to press Allow).

        Returns True only once a real token has been saved: a channel that opens
        without a token does not survive a reconnect, so it is not a pairing."""
        conn = await self.get(tv)
        await conn.reset_connection()  # lock-safe reset before fresh handshake
        remove_legacy_placeholder_token(conn.token_file)

        try:
            await asyncio.wait_for(conn._ensure_remote(), timeout=self.PAIR_TIMEOUT_SECS)
        except asyncio.TimeoutError:
            log.warning("pair: connection timed out for TV %s", tv.id)
            return False
        except Exception as e:
            log.warning("pair: connection failed for TV %s: %s", tv.id, e)
            return False

        if has_real_token(conn.token_file):
            log.info("pair: token saved for TV %s", tv.id)
            return True
        log.warning("pair: TV %s accepted the connection but issued no token", tv.id)
        return False

    async def power_on(self, tv: TV) -> bool:
        if not tv.mac or not HAS_WOL:
            return False
        try:
            send_magic_packet(tv.mac)
            return True
        except Exception as e:
            log.warning("WoL failed: %s", e)
            return False

    async def power_off(self, tv: TV) -> bool:
        conn = await self.get(tv)
        try:
            remote = await conn._ensure_remote()
            await remote.send_command(("KEY_POWER",))
            return True
        except Exception as e:
            log.warning("power_off failed: %s", e)
            await conn.drop_remote()
            return False

    async def _art_call(self, tv: TV, what: str, fn, default: Any = None) -> Any:
        """Run ``await fn(art)`` in an art session; log and return ``default`` on error."""
        conn = await self.get(tv)
        try:
            async with conn.art_session() as art:
                return await fn(art)
        except Exception as e:
            log.warning("%s failed for TV %s: %s", what, tv.id, e, exc_info=True)
            return default

    async def set_artmode(self, tv: TV, on: bool) -> bool:
        async def call(art):
            await art.set_artmode("on" if on else "off")
            return True
        return await self._art_call(tv, "set_artmode", call, False)

    async def upload_image(self, tv: TV, file_path: str, matte: str = "none",
                           file_type: str = "JPEG") -> str | None:
        try:
            with open(file_path, "rb") as f:
                data = f.read()
        except OSError as e:
            log.warning("upload_image: cannot read %s: %s", file_path, e)
            return None

        async def call(art):
            log.debug("upload_image: uploading %s to TV %s", file_path, tv.id)
            content_id = await art.upload(data, file_type=file_type, matte=matte, portrait_matte=matte)
            log.info("upload_image: TV %s accepted %s → remote_id=%s", tv.id, file_path, content_id)
            return content_id
        return await self._art_call(tv, f"upload_image {file_path}", call)

    async def select_image(self, tv: TV, remote_id: str, show: bool = True) -> bool:
        async def call(art):
            await art.select_image(remote_id, show=show)
            return True
        ok = await self._art_call(tv, f"select_image {remote_id}", call, False)
        if ok:
            await ws_manager.broadcast({"type": "art_changed", "tv_id": tv.id, "remote_id": remote_id})
        return ok

    async def delete_image(self, tv: TV, remote_id: str) -> bool:
        async def call(art):
            await art.delete_list([remote_id])
            return True
        return await self._art_call(tv, f"delete_image {remote_id}", call, False)

    async def list_images(self, tv: TV) -> list[dict]:
        async def call(art):
            res = await art.available()
            return res if isinstance(res, list) else []
        return await self._art_call(tv, "list_images", call, [])

    async def get_thumbnail(self, tv: TV, content_id: str) -> bytes | None:
        async def call(art):
            data = await art.get_thumbnail(content_id, as_bytes=True)
            return data if isinstance(data, (bytes, bytearray)) else None
        return await self._art_call(tv, f"get_thumbnail {content_id}", call)

    async def set_matte(self, tv: TV, remote_id: str, matte: str) -> bool:
        async def call(art):
            await art.change_matte(remote_id, matte)
            return True
        return await self._art_call(tv, f"set_matte {remote_id}", call, False)

    async def get_settings(self, tv: TV) -> dict:
        async def call(art):
            out: dict = {}
            for key, fn in [
                ("brightness", "get_brightness"),
                ("color_temp", "get_color_temperature"),
                ("slideshow", "get_slideshow_status"),
                ("motion_timer", "get_motion_timer"),
                ("motion_sensitivity", "get_motion_sensitivity"),
                ("brightness_sensor", "get_brightness_sensor_setting"),
            ]:
                try:
                    if hasattr(art, fn):
                        out[key] = normalize_art_setting(key, await getattr(art, fn)())
                except Exception:
                    out[key] = None
            return out
        return await self._art_call(tv, "get_settings", call, {})

    async def apply_settings(self, tv: TV, payload: dict) -> dict:
        async def call(art):
            result: dict = {}
            mapping = {
                "brightness": "set_brightness",
                "color_temp": "set_color_temperature",
                "motion_timer": "set_motion_timer",
                "motion_sensitivity": "set_motion_sensitivity",
                "brightness_sensor": "set_brightness_sensor_setting",
            }
            for key, fn in mapping.items():
                if payload.get(key) is not None and hasattr(art, fn):
                    try:
                        await getattr(art, fn)(payload[key])
                        result[key] = "ok"
                    except Exception as e:
                        result[key] = str(e)
            if payload.get("shuffle") is not None or payload.get("slideshow_interval") is not None:
                try:
                    await art.set_slideshow_status(
                        duration=payload.get("slideshow_interval") or 3,
                        type="shuffle" if payload.get("shuffle") else "serial",
                        category=2,
                    )
                    result["slideshow"] = "ok"
                except Exception as e:
                    result["slideshow"] = str(e)
            return result

        conn = await self.get(tv)
        try:
            async with conn.art_session() as art:
                return await call(art)
        except Exception as e:
            return {"_error": str(e)}

    async def list_mattes(self, tv: TV) -> list[str]:
        async def call(art):
            return normalize_matte_list(await art.get_matte_list())
        return await self._art_call(tv, "list_mattes", call, [])

    async def get_current(self, tv: TV) -> dict | None:
        async def call(art):
            return await art.get_current()
        return await self._art_call(tv, "get_current", call)

    async def device_info(self, tv: TV) -> dict:
        async def call(art):
            return await art.get_device_info() if hasattr(art, "get_device_info") else {}
        return await self._art_call(tv, "device_info", call, {})


tv_manager = TVManager()
