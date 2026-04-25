from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Boolean, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base


class TizenBrewState(Base):
    __tablename__ = "tizenbrew_state"
    __table_args__ = (UniqueConstraint("tv_id", name="uq_tizenbrew_state_tv"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tv_id: Mapped[int] = mapped_column(Integer, ForeignKey("tvs.id", ondelete="CASCADE"))
    tizen_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tizen_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    developer_mode_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    sdb_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    tizenbrew_installed: Mapped[bool] = mapped_column(Boolean, default=False)
    tizenbrew_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    certificate_profile: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class TizenBrewInstalledApp(Base):
    __tablename__ = "tizenbrew_installed_apps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tv_id: Mapped[int] = mapped_column(Integer, ForeignKey("tvs.id", ondelete="CASCADE"))
    app_name: Mapped[str] = mapped_column(String(256))
    app_source: Mapped[str] = mapped_column(String(512))
    installed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    wgt_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
