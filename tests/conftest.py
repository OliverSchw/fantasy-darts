import os
import tempfile
from pathlib import Path

# Muss vor dem Import der App gesetzt sein: eigene Wegwerf-Datenbank für die Tests.
_tmp = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
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
