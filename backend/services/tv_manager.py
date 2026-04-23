from __future__ import annotations
import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Optional
from sqlalchemy import select
from ..config import settings
from ..database import SessionLocal
from ..models.tv import TV
from .ws_manager import ws_manager

log = logging.getLogger(__name__)

# samsungtvws (NickWaterton fork) optional import — guarded so app still boots
# even if user hasn't installed deps yet.
try:
    from samsungtvws.async_art import SamsungTVAsyncArt
    from samsungtvws.async_remote import SamsungTVWSAsyncRemote
    HAS_LIB = True
except Exception as e:  # pragma: no cover
    log.warning("samsungtvws not available: %s", e)
    SamsungTVAsyncArt = None  # type: ignore
    SamsungTVWSAsyncRemote = None  # type: ignore
    HAS_LIB = False

try:
    from wakeonlan import send_magic_packet
    HAS_WOL = True
except Exception:
    send_magic_packet = None  # type: ignore
    HAS_WOL = False


def token_path_for(tv: TV) -> str:
    return tv.token_path or os.path.join(settings.TOKEN_DIR, f"tv_{tv.id}.token")


class TVConnection:
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

    async def _ensure_art(self) -> Any:
        if not HAS_LIB:
            raise RuntimeError("samsungtvws library not installed")
        if self.art is None:
            self.art = SamsungTVAsyncArt(
                host=self.ip, port=self.port, token_file=self.token_file, name=self.name or "FrameManager"
            )
            await self.art.start_listening()
        return self.art

    async def _ensure_remote(self) -> Any:
        if not HAS_LIB:
            raise RuntimeError("samsungtvws library not installed")
        if self.remote is None:
            self.remote = SamsungTVWSAsyncRemote(
                host=self.ip, port=self.port, token_file=self.token_file, name=self.name or "FrameManager"
            )
            await self.remote.start_listening()
        return self.remote

    async def close(self) -> None:
        self._closed = True
        for c in (self.art, self.remote):
            if c is not None:
                try:
                    await c.close()
                except Exception:
                    pass
        self.art = None
        self.remote = None

    async def safe(self, fn, *a, **kw):
        async with self.lock:
            try:
                return await fn(*a, **kw)
            except Exception as e:
                log.warning("TV %s call failed: %s", self.tv_id, e)
                # drop connection so next call retries
                await self.close()
                raise


class TVManager:
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
                if status != conn.last_status:
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
                art = await conn._ensure_art()
                artmode = await art.get_artmode()
                current = None
                try:
                    cur = await art.get_current()
                    current = cur.get("content_id") if isinstance(cur, dict) else None
                except Exception:
                    pass
                tv.last_seen = datetime.utcnow()
                await s.commit()
                return {"online": True, "artmode": (artmode == "on" or artmode is True),
                        "current": current}
            except Exception as e:
                return {"online": False, "artmode": None, "current": None, "error": str(e)}

    # ── High-level operations ────────────────────────────────────────────────
    async def pair(self, tv: TV, timeout: float = 90.0) -> bool:
        """Open a connection so the Allow prompt appears; success when token saved."""
        conn = await self.get(tv)
        try:
            await asyncio.wait_for(conn._ensure_art(), timeout=timeout)
            return os.path.exists(conn.token_file) and os.path.getsize(conn.token_file) > 0
        except Exception as e:
            log.warning("pair failed: %s", e)
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
            return False

    async def set_artmode(self, tv: TV, on: bool) -> bool:
        conn = await self.get(tv)
        try:
            art = await conn._ensure_art()
            await art.set_artmode("on" if on else "off")
            return True
        except Exception as e:
            log.warning("set_artmode failed: %s", e)
            return False

    async def upload_image(self, tv: TV, file_path: str, matte: str = "none",
                           file_type: str = "JPEG") -> str | None:
        conn = await self.get(tv)
        try:
            art = await conn._ensure_art()
            with open(file_path, "rb") as f:
                data = f.read()
            content_id = await art.upload(data, file_type=file_type, matte=matte)
            return content_id
        except Exception as e:
            log.warning("upload_image failed: %s", e)
            return None

    async def select_image(self, tv: TV, remote_id: str, show: bool = True) -> bool:
        conn = await self.get(tv)
        try:
            art = await conn._ensure_art()
            await art.select_image(remote_id, show=show)
            await ws_manager.broadcast({"type": "art_changed", "tv_id": tv.id, "remote_id": remote_id})
            return True
        except Exception as e:
            log.warning("select_image failed: %s", e)
            return False

    async def delete_image(self, tv: TV, remote_id: str) -> bool:
        conn = await self.get(tv)
        try:
            art = await conn._ensure_art()
            await art.delete_list([remote_id])
            return True
        except Exception as e:
            log.warning("delete_image failed: %s", e)
            return False

    async def list_images(self, tv: TV) -> list[dict]:
        conn = await self.get(tv)
        try:
            art = await conn._ensure_art()
            res = await art.available()
            return res if isinstance(res, list) else []
        except Exception as e:
            log.warning("list_images failed: %s", e)
            return []

    async def get_thumbnail(self, tv: TV, content_id: str) -> bytes | None:
        conn = await self.get(tv)
        try:
            art = await conn._ensure_art()
            data = await art.get_thumbnail(content_id, as_bytes=True)
            return data if isinstance(data, (bytes, bytearray)) else None
        except Exception as e:
            log.warning("get_thumbnail failed: %s", e)
            return None

    async def set_matte(self, tv: TV, remote_id: str, matte: str) -> bool:
        conn = await self.get(tv)
        try:
            art = await conn._ensure_art()
            await art.change_matte(remote_id, matte)
            return True
        except Exception as e:
            log.warning("set_matte failed: %s", e)
            return False

    async def get_settings(self, tv: TV) -> dict:
        conn = await self.get(tv)
        out: dict = {}
        try:
            art = await conn._ensure_art()
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
                        out[key] = await getattr(art, fn)()
                except Exception:
                    out[key] = None
        except Exception as e:
            log.warning("get_settings failed: %s", e)
        return out

    async def apply_settings(self, tv: TV, payload: dict) -> dict:
        conn = await self.get(tv)
        result: dict = {}
        try:
            art = await conn._ensure_art()
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
        except Exception as e:
            result["_error"] = str(e)
        return result

    async def list_mattes(self, tv: TV) -> list[str]:
        conn = await self.get(tv)
        try:
            art = await conn._ensure_art()
            res = await art.get_matte_list()
            if isinstance(res, list):
                return res
            return list(res) if res else []
        except Exception as e:
            log.warning("list_mattes failed: %s", e)
            return []

    async def get_current(self, tv: TV) -> dict | None:
        conn = await self.get(tv)
        try:
            art = await conn._ensure_art()
            return await art.get_current()
        except Exception:
            return None

    async def device_info(self, tv: TV) -> dict:
        conn = await self.get(tv)
        try:
            art = await conn._ensure_art()
            return await art.get_device_info() if hasattr(art, "get_device_info") else {}
        except Exception as e:
            log.warning("device_info failed: %s", e)
            return {}


tv_manager = TVManager()
