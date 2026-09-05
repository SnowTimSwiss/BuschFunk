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


# (Tabelle, Spalte, SQL-Definition) - wird nachgezogen, falls die Spalte in einer
# schon bestehenden DB fehlt. create_all() legt nur fehlende *Tabellen* an, nicht
# fehlende Spalten; ohne das hier würde ein Update auf einem laufenden Pi crashen.
_ADD_COLUMNS = [
    ("buses", "volume", "REAL NOT NULL DEFAULT 1.0"),
    ("segments", "media_original_name", "VARCHAR"),
    ("segments", "media_role", "VARCHAR NOT NULL DEFAULT 'full'"),
    ("segments", "media_trigger", "VARCHAR NOT NULL DEFAULT 'manual'"),
]

# Spalten aus früheren Versionen, die es nicht mehr gibt (Notfall-Buttons entfernt).
_DROP_COLUMNS = [
    ("live_state", "notfall_mode"),
    ("live_state", "notfall_message"),
    ("live_state", "notfall_acked"),
]


def _existing_columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


def _migrate() -> None:
    with engine.begin() as conn:
        tables = {
            r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        for table, column, ddl in _ADD_COLUMNS:
            if table in tables and column not in _existing_columns(conn, table):
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        for table, column in _DROP_COLUMNS:
            if table in tables and column in _existing_columns(conn, table):
                conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
        # Platzhalter-Geräte aus dem alten Dummy-Backend wegräumen: die tauchten
        # dauerhaft als "nicht verbunden" auf, obwohl nie etwas dranhing.
        if "buses" in tables:
            conn.execute(text("DELETE FROM buses WHERE device_id LIKE 'dummy:%'"))


def init_db() -> None:
    from . import models  # noqa: F401  (register models on Base.metadata)

    settings.database_file.parent.mkdir(parents=True, exist_ok=True)
    settings.media_path.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _migrate()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
