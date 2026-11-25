import os
import tempfile
from pathlib import Path

# Muss vor dem Import der App gesetzt sein: eigene Wegwerf-Datenbank für die Tests.
# Standard ist SQLite; mit TEST_DATABASE_URL=postgresql://... laufen die Tests gegen Postgres
# (Achtung: die Tests löschen und erzeugen dort alle Tabellen - nur eine leere Test-DB verwenden!).
_tmp = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["SEASON"] = "wm2026"

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import models  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.rules import load_rules  # noqa: E402
from app.season import import_season  # noqa: E402


@pytest.fixture
def rules():
    return load_rules("wm2026")


@pytest.fixture
def db():
    from app.darts import rating
    rating._cache.clear()  # Zwischenspeicher für Elo/Erfolge gehört zur alten Test-Datenbank
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        import_season(session, "wm2026")
        yield session


@pytest.fixture
def season(db):
    return db.scalar(select(models.Season))


@pytest.fixture
def make_user(db):
    def _make(name="olli", password="secret123", admin=False):
        u = models.User(username=name, password_hash=hash_password(password), is_admin=admin)
        db.add(u)
        db.commit()
        return u

    return _make


def double_answer(game, score, darts=None):
    """So antwortet ein Spieler in Tests auf "Darts at the double?": 1 beim Checkout, sonst 0 - und nur, wenn
    die Seite überhaupt fragen würde (sonst None)."""
    from app.darts import service
    from app.darts.engine import make_visit
    from app.darts.throws import ask_double_darts
    st = service.game_state(game)
    rest = st.remaining[st.side(st.turn)]
    try:
        v = make_visit(st, score, darts)
    except Exception:
        return None
    if not ask_double_darts(rest, score, v.bust, v.checkout):
        return None
    return 1 if v.checkout else 0
