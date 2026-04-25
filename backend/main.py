from __future__ import annotations
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .config import settings
from .database import init_db
from .services.tv_manager import tv_manager
from .services.scheduler import load_all as load_schedules, shutdown as sched_shutdown
from .services.watcher import watcher
from .routers import tv, art, images, schedule, sources, ws as ws_router, meta, tizenbrew as tizenbrew_router
from .models import tizenbrew as _tizenbrew_models  # noqa: F401  (register tables)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("sawsube")

# Verbose DEBUG for TV-related modules so connection failures are fully visible
for _tv_logger in ("backend.services.tv_manager", "samsungtvws", "samsungtvws.async_art",
                   "samsungtvws.async_remote", "samsungtvws.encrypted"):
    logging.getLogger(_tv_logger).setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await load_schedules()
    loop = asyncio.get_running_loop()
    watcher.start()
    await watcher.reload(loop)
    log.info("SAWSUBE up on %s:%s", settings.HOST, settings.PORT)
    try:
        yield
    finally:
        await sched_shutdown()
        watcher.stop()
        await tv_manager.shutdown()


app = FastAPI(title="SAWSUBE", version="1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tv.router)
app.include_router(art.router)
app.include_router(images.router)
app.include_router(schedule.router)
app.include_router(sources.router)
app.include_router(meta.router)
app.include_router(ws_router.router)
app.include_router(tizenbrew_router.router)


@app.get("/api/health")
async def health():
    return {"ok": True}


# Serve frontend static if built
if os.path.isdir(settings.FRONTEND_DIST):
    assets_dir = os.path.join(settings.FRONTEND_DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    from fastapi import HTTPException

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        # Never serve SPA for API or WS routes — let them 404 properly
        if full_path.startswith("api/") or full_path == "ws" or full_path.startswith("ws/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = os.path.join(settings.FRONTEND_DIST, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(settings.FRONTEND_DIST, "index.html"))


def main() -> None:
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.HOST, port=settings.PORT, reload=False)


if __name__ == "__main__":
    main()
