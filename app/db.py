from collections.abc import Iterator

from sqlalchemy import create_engine, event
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


def create_tables() -> None:
    from . import models  # noqa: F401  (registriert die Tabellen)

    Base.metadata.create_all(engine)
