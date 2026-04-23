from __future__ import annotations
from datetime import datetime, time
from sqlalchemy import String, Integer, DateTime, Boolean, JSON, ForeignKey, Time
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tv_id: Mapped[int] = mapped_column(ForeignKey("tvs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128), default="Schedule")
    mode: Mapped[str] = mapped_column(String(16), default="random")  # random|sequential|weighted
    source_filter: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    interval_mins: Mapped[int] = mapped_column(Integer, default=60)
    time_from: Mapped[time | None] = mapped_column(Time, nullable=True)
    time_to: Mapped[time | None] = mapped_column(Time, nullable=True)
    days_of_week: Mapped[str] = mapped_column(String(16), default="0,1,2,3,4,5,6")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
