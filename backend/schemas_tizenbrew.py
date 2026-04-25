from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class TizenInfoResponse(BaseModel):
    tv_id: int
    ip: str
    developer_mode: bool
    developer_ip: str | None = None
    tizen_version: str | None = None
    tizen_year: int | None = None
    model_name: str | None = None
    requires_certificate: bool = False
    error: str | None = None


class SdbStatusResponse(BaseModel):
    tv_id: int
    sdb_available: bool
    tizen_available: bool
    tv_connected: bool
    error: str | None = None


class ToolsStatus(BaseModel):
    sdb_path: str | None
    tizen_path: str | None
    found: bool


class CertificateStatus(BaseModel):
    tv_id: int
    profile_name: str | None = None
    created: bool = False
    samsung_account_required: bool = False
    error: str | None = None


class CertificateCreate(BaseModel):
    profile_name: str = "SAWSUBE"
    password: str
    country: str = "GB"
    state: str = "London"
    city: str = "London"
    org: str = "SAWSUBE"


class TizenBrewStateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tv_id: int
    tizen_version: str | None
    tizen_year: int | None
    developer_mode_detected: bool
    sdb_connected: bool
    tizenbrew_installed: bool
    tizenbrew_version: str | None
    certificate_profile: str | None
    last_checked: datetime | None
    notes: str | None


class InstallProgressEvent(BaseModel):
    type: str = "tizenbrew_install_progress"
    tv_id: int
    step: str
    message: str
    progress: int = 0


class AppDefinition(BaseModel):
    id: str
    name: str
    description: str
    icon_url: str | None = None
    source_type: str  # "github" | "wgt_url" | "custom"
    source: str
    category: str = "Misc"


class InstalledAppOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tv_id: int
    app_name: str
    app_source: str
    installed_at: datetime
    wgt_path: str | None
    version: str | None


class CustomModuleCreate(BaseModel):
    package_name: str
    app_name: str
    package_type: str = Field(pattern="^(app|mods)$")
    website_url: str | None = None
    app_path: str | None = None
    keys: list[str] = []
    service_file: str | None = None
    evaluate_on_start: bool = False
    description: str | None = None


class ModuleScaffoldResponse(BaseModel):
    package_json: dict[str, Any]
    readme: str
    instructions: str
    service_file: str | None = None
    inject_file: str | None = None


class JobStarted(BaseModel):
    started: bool = True
    job_id: str
