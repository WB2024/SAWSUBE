from __future__ import annotations
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    TV_DEFAULT_IP: str = ""
    IMAGE_FOLDER: str = "./data/images"
    DB_PATH: str = "./data/framemanager.db"
    TOKEN_DIR: str = "./data/tokens"
    IMAGE_CACHE_DIR: str = "./data/cache"
    THUMBNAIL_DIR: str = "./data/thumbnails"
    TV_RESOLUTION: str = "4K"  # 4K | 1080p
    PORTRAIT_HANDLING: str = "blur"  # blur | crop | skip
    UNSPLASH_API_KEY: str = ""
    RIJKSMUSEUM_API_KEY: str = ""
    REDDIT_USER_AGENT: str = "frame-manager/1.0 (local self-hosted)"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    POLL_INTERVAL_SECS: int = 20
    FRONTEND_DIST: str = "./frontend/dist"

    @property
    def resolution_tuple(self) -> tuple[int, int]:
        return (3840, 2160) if self.TV_RESOLUTION.upper() == "4K" else (1920, 1080)


settings = Settings()

# Ensure directories exist
for p in [settings.IMAGE_FOLDER, settings.TOKEN_DIR, settings.IMAGE_CACHE_DIR,
          settings.THUMBNAIL_DIR, os.path.dirname(settings.DB_PATH) or "."]:
    Path(p).mkdir(parents=True, exist_ok=True)
