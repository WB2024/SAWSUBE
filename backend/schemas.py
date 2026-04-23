from __future__ import annotations
from datetime import datetime, time
from typing import Any
from pydantic import BaseModel, ConfigDict


class TVCreate(BaseModel):
    name: str = "Frame TV"
    ip: str
    mac: str | None = None
    port: int = 8002


class TVOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    ip: str
    mac: str | None
    port: int
    model: str | None
    year: str | None
    last_seen: datetime | None
    added_at: datetime


class TVStatus(BaseModel):
    id: int
    online: bool
    artmode: bool | None = None
    current: str | None = None
    paired: bool = False
    error: str | None = None


class ArtSettings(BaseModel):
    brightness: int | None = None
    color_temp: int | None = None
    shuffle: bool | None = None
    slideshow_interval: int | None = None
    motion_timer: int | None = None
    motion_sensitivity: int | None = None
    brightness_sensor: bool | None = None


class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    file_hash: str
    file_size: int
    width: int
    height: int
    source: str
    source_meta: dict | None
    uploaded_at: datetime
    is_favourite: bool
    tags: str | None


class TVImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tv_id: int
    image_id: int
    remote_id: str | None
    uploaded_at: datetime
    is_on_tv: bool
    matte: str


class ScheduleCreate(BaseModel):
    tv_id: int
    name: str = "Schedule"
    mode: str = "random"
    source_filter: dict | None = None
    interval_mins: int = 60
    time_from: time | None = None
    time_to: time | None = None
    days_of_week: str = "0,1,2,3,4,5,6"
    is_active: bool = True


class ScheduleOut(ScheduleCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class FolderCreate(BaseModel):
    path: str
    is_active: bool = True
    auto_display: bool = False


class FolderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    path: str
    is_active: bool
    auto_display: bool


class TagsUpdate(BaseModel):
    tags: str


class MatteSet(BaseModel):
    matte: str  # e.g. "modern_apricot" per Samsung naming


class CurrentSet(BaseModel):
    tv_image_id: int


class ImportPayload(BaseModel):
    url: str | None = None
    id: str | None = None
    meta: dict[str, Any] | None = None
