from datetime import datetime, timezone

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Track(Base):
    """Eine hochgeladene Audiodatei: Musikstueck, Jingle oder Aufnahme."""

    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(unique=True)  # Datei in media/
    original_name: Mapped[str] = mapped_column(default="")
    title: Mapped[str] = mapped_column(default="")
    kind: Mapped[str] = mapped_column(default="music")  # music | jingle
    duration: Mapped[float] = mapped_column(default=0.0)  # Sekunden, 0 = unbekannt
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    items: Mapped[list["PlaylistItem"]] = relationship(
        back_populates="track", cascade="all, delete-orphan"
    )


class Playlist(Base):
    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(default="Neue Playlist")
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    items: Mapped[list["PlaylistItem"]] = relationship(
        back_populates="playlist",
        cascade="all, delete-orphan",
        order_by="PlaylistItem.position",
    )


class PlaylistItem(Base):
    __tablename__ = "playlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"))
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(default=0)

    playlist: Mapped["Playlist"] = relationship(back_populates="items")
    track: Mapped["Track"] = relationship(back_populates="items")


class Bus(Base):
    __tablename__ = "buses"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str] = mapped_column(default="Neues Geraet")
    direction: Mapped[str] = mapped_column(default="in")  # in (Eingang) | out (Ausgang)
    is_muted: Mapped[bool] = mapped_column(default=True)
    volume: Mapped[float] = mapped_column(default=1.0)  # 0.0 .. 1.5
    last_seen_active: Mapped[datetime | None] = mapped_column(nullable=True)


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
    """Singleton-Zeile (id=1). Haelt nur noch, ob die Mikrofone offen sind -
    das ueberlebt Neustarts und Self-Updates."""

    __tablename__ = "live_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    on_air: Mapped[bool] = mapped_column(default=False)
