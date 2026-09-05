from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    f"sqlite:///{settings.database_file}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# Tabellen aus frueheren Versionen (Tagesplan/Ablauf/Sendezeiten) - die gibt es
# nicht mehr, ihre Audiodateien werden vorher in die Mediathek uebernommen.
_DROP_TABLES = ["segments", "shows", "schedule_entries"]

# (Tabelle, Spalte, SQL) - create_all() legt nur fehlende *Tabellen* an, nicht
# fehlende Spalten; ohne das hier wuerde ein Update auf einem laufenden Pi crashen.
_ADD_COLUMNS = [
    ("buses", "volume", "REAL NOT NULL DEFAULT 1.0"),
]


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}


def _columns(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def _adopt_legacy_media(conn) -> None:
    """Dateien, die frueher an einem Segment hingen, als Titel in die Mediathek
    uebernehmen - sonst waeren sie nach dem Update unerreichbar auf der Platte."""
    from .audio.probe import probe_duration

    columns = _columns(conn, "segments")
    if "media_file" not in columns:
        return
    # "media_original_name" gibt es erst seit einer spaeteren Version.
    name_column = "media_original_name" if "media_original_name" in columns else "media_file"
    rows = conn.execute(
        text(
            f"SELECT media_file, {name_column}, title FROM segments "
            "WHERE media_file IS NOT NULL AND media_file != ''"
        )
    ).fetchall()
    known = {r[0] for r in conn.execute(text("SELECT filename FROM tracks"))}
    for filename, original_name, title in rows:
        if filename in known:
            continue
        path = settings.media_path / filename
        if not path.exists():
            continue
        known.add(filename)
        conn.execute(
            text(
                "INSERT INTO tracks (filename, original_name, title, kind, duration, created_at) "
                "VALUES (:f, :o, :t, 'music', :d, CURRENT_TIMESTAMP)"
            ),
            {
                "f": filename,
                "o": original_name or filename,
                "t": (title or original_name or filename).strip(),
                "d": probe_duration(path),
            },
        )


def _migrate() -> None:
    with engine.begin() as conn:
        tables = _tables(conn)
        if "segments" in tables and "tracks" in tables:
            _adopt_legacy_media(conn)
        for table in _DROP_TABLES:
            if table in tables:
                conn.execute(text(f"DROP TABLE {table}"))
        # live_state hiess frueher anders befuellt (Tagesplan-Zeiger, Countdown).
        if "live_state" in tables and "active_show_id" in _columns(conn, "live_state"):
            conn.execute(text("DROP TABLE live_state"))
        for table, column, ddl in _ADD_COLUMNS:
            if table in tables and column not in _columns(conn, table):
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        # Platzhalter-Geraete aus dem alten Dummy-Backend wegraeumen.
        if "buses" in tables:
            conn.execute(text("DELETE FROM buses WHERE device_id LIKE 'dummy:%'"))


def init_db() -> None:
    from . import models  # noqa: F401  (register models on Base.metadata)

    settings.database_file.parent.mkdir(parents=True, exist_ok=True)
    settings.media_path.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _migrate()
    # Nach einem DROP fehlende Tabellen (live_state) direkt wieder anlegen.
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
