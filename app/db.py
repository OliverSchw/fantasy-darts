from collections.abc import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = get_settings().sqlalchemy_url
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite prüft Fremdschlüssel nur mit diesem Pragma
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return eng
    # pool_pre_ping: Verbindungen nach Pause (Neon scale-to-zero, Serverless) prüfen
    return create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=2, pool_recycle=300)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


# Spalten, die nach der ersten Version dazugekommen sind. create_all() legt nur neue Tabellen an,
# fügt aber keine Spalten zu bestehenden hinzu - das passiert hier (idempotent).
ADDED_COLUMNS = [
    ("matches", "scheduled_at", {"sqlite": "DATETIME", "postgresql": "TIMESTAMP WITH TIME ZONE"}),
    ("users", "avatar_version", {"sqlite": "INTEGER", "postgresql": "INTEGER"}),
    ("darts_games", "tournament_match_id", {"sqlite": "INTEGER", "postgresql": "INTEGER"}),
    ("tournament_entries", "group_no", {"sqlite": "INTEGER", "postgresql": "INTEGER"}),
    ("tournament_matches", "group_no", {"sqlite": "INTEGER", "postgresql": "INTEGER"}),
    ("tournament_matches", "board", {"sqlite": "INTEGER", "postgresql": "INTEGER"}),
    ("darts_games", "team_size", {"sqlite": "INTEGER DEFAULT 1", "postgresql": "INTEGER DEFAULT 1"}),
    ("darts_games", "winner_side", {"sqlite": "INTEGER", "postgresql": "INTEGER"}),
]


def migrate(eng=None) -> list[str]:
    eng = eng or engine
    insp = inspect(eng)
    tables = set(insp.get_table_names())
    added = []
    with eng.begin() as conn:
        for table, column, types in ADDED_COLUMNS:
            if table in tables and column not in {c["name"] for c in insp.get_columns(table)}:
                col_type = types.get(eng.dialect.name, "TIMESTAMP")
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                added.append(f"{table}.{column}")
    return added


def create_tables() -> None:
    from . import models  # noqa: F401  (registriert die Tabellen)

    Base.metadata.create_all(engine)
    migrate()
