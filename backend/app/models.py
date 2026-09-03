from datetime import datetime, timezone

from sqlalchemy import ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Show(Base):
    __tablename__ = "shows"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(default="Neuer Tag")
    position: Mapped[int] = mapped_column(default=0)

    segments: Mapped[list["Segment"]] = relationship(
        back_populates="show",
        cascade="all, delete-orphan",
        order_by="Segment.position",
        primaryjoin="and_(Show.id==Segment.show_id, Segment.parent_id.is_(None))",
        viewonly=False,
    )


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id", ondelete="CASCADE"))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("segments.id", ondelete="CASCADE"), nullable=True
    )
    position: Mapped[int] = mapped_column(default=0)

    type: Mapped[str] = mapped_column(default="song")
    title: Mapped[str] = mapped_column(default="Neues Segment")
    time: Mapped[str | None] = mapped_column(nullable=True)  # "HH:MM", orientierend
    planned_duration: Mapped[int] = mapped_column(default=0)  # Sekunden
    fixed: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str | None] = mapped_column(nullable=True)
    media_file: Mapped[str | None] = mapped_column(nullable=True)
    auto_route: Mapped[list[int]] = mapped_column(JSON, default=list)

    show: Mapped["Show"] = relationship(back_populates="segments", foreign_keys=[show_id])
    children: Mapped[list["Segment"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="Segment.position",
        foreign_keys=[parent_id],
    )
    parent: Mapped["Segment | None"] = relationship(
        back_populates="children", remote_side=[id], foreign_keys=[parent_id]
    )


class Bus(Base):
    __tablename__ = "buses"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str] = mapped_column(default="Neuer Bus")
    is_muted: Mapped[bool] = mapped_column(default=True)
    last_seen_active: Mapped[datetime | None] = mapped_column(nullable=True)


class ScheduleEntry(Base):
    __tablename__ = "schedule_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(default="")
    from_time: Mapped[str] = mapped_column(default="")
    to_time: Mapped[str] = mapped_column(default="")
    title: Mapped[str] = mapped_column(default="")
    public: Mapped[bool] = mapped_column(default=True)
    position: Mapped[int] = mapped_column(default=0)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    password_hash: Mapped[str] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SetupCode(Base):
    """Einmal-Code, den der Pi beim allerersten Start generiert und ins Log schreibt."""

    __tablename__ = "setup_codes"
    __table_args__ = (UniqueConstraint("id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column()
    used: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class LiveState(Base):
    """Singleton-Zeile (id=1), hält den Live-Zustand über Neustarts/Self-Updates hinweg."""

    __tablename__ = "live_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    active_show_id: Mapped[int | None] = mapped_column(
        ForeignKey("shows.id", ondelete="SET NULL"), nullable=True
    )
    current_segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("segments.id", ondelete="SET NULL"), nullable=True
    )
    segment_started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    elapsed_offset_seconds: Mapped[int] = mapped_column(default=0)
    is_on_air: Mapped[bool] = mapped_column(default=False)
    notfall_mode: Mapped[str | None] = mapped_column(nullable=True)  # sos | mute_all | unterbruch
    notfall_message: Mapped[str | None] = mapped_column(nullable=True)
    notfall_acked: Mapped[bool] = mapped_column(default=True)
