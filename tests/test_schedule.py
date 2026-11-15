from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text

from app import models
from app.db import migrate
from app.main import app
from app.season import season_players
from app.teams import TeamInput, save_team


def test_migration_adds_missing_column(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as c:  # Tabelle wie in der ersten Version, ohne scheduled_at
        c.execute(text("CREATE TABLE matches (id INTEGER PRIMARY KEY, round INTEGER)"))
    assert migrate(eng) == ["matches.scheduled_at"]
    assert "scheduled_at" in {c["name"] for c in inspect(eng).get_columns("matches")}
    assert migrate(eng) == []  # idempotent


@pytest.fixture
def admin(db, make_user):
    make_user("boss", admin=True)
    with TestClient(app) as c:
        c.post("/login", data={"username": "boss", "password": "secret123"})
        yield c


def _local_input(dt):
    return dt.strftime("%Y-%m-%dT%H:%M")


def test_admin_sets_times_and_everyone_sees_them(admin, db, season, make_user):
    tz = ZoneInfo("Europe/Berlin")
    today_1930 = datetime.now(tz).replace(hour=19, minute=30, second=0, microsecond=0)
    m0, m1 = (db.scalar(select(models.Match).where(models.Match.round == 1, models.Match.slot == s)) for s in (0, 1))
    r2 = db.scalar(select(models.Match).where(models.Match.round == 2, models.Match.slot == 0))

    assert admin.get("/admin/schedule?round=1").status_code == 200
    admin.post("/admin/schedule?round=1", data={f"time_{m0.id}": _local_input(today_1930),
                                               f"time_{m1.id}": _local_input(today_1930 + timedelta(hours=1))})
    # Runde 2 schon ansetzen, obwohl die Spieler noch offen sind
    admin.post("/admin/schedule?round=2", data={f"time_{r2.id}": _local_input(today_1930 + timedelta(days=2))})
    db.expire_all()
    assert db.get(models.Match, m0.id).scheduled_at is not None

    with TestClient(app) as guest:
        page = guest.get("/schedule").text
        assert "19:30" in page and "20:30" in page and "Today" in page
        p0 = db.get(models.Player, m0.p1_id)
        assert p0.name in page
        assert " / " in page  # Runde 2: "A / B"
        home = guest.get("/").text

        assert "19:30" in home and "Full schedule" in home
        assert "today 19:30" in guest.get(f"/players/{p0.id}").text

    # Zeit wieder entfernen
    admin.post("/admin/schedule?round=1", data={f"time_{m1.id}": ""})
    db.expire_all()
    assert db.get(models.Match, m1.id).scheduled_at is None


def test_schedule_filter_my_players(db, season, make_user):
    u = make_user("olli")
    m0 = db.scalar(select(models.Match).where(models.Match.round == 1, models.Match.slot == 0))
    m9 = db.scalar(select(models.Match).where(models.Match.round == 1, models.Match.slot == 9))
    players = season_players(db, season)
    others = [p.id for p in sorted(players.values(), key=lambda p: p.price)
              if p.id not in (m0.p1_id, m0.p2_id, m9.p1_id, m9.p2_id)][:14]
    ids = [m0.p1_id] + others
    save_team(db, models.Team(season_id=season.id, user_id=u.id), TeamInput("T", ids, others[0], others[0], others[0]))
    when = (datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(days=1)).astimezone(timezone.utc)
    m0.scheduled_at, m9.scheduled_at = when, when + timedelta(hours=1)
    db.commit()

    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        all_page = c.get("/schedule").text
        mine_page = c.get("/schedule?mine=1").text
    name9 = players[m9.p1_id].name
    assert name9 in all_page and name9 not in mine_page
    assert players[m0.p1_id].name in mine_page


def test_schedule_admin_only(db, make_user):
    make_user("olli")
    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        assert c.get("/admin/schedule").status_code == 403
        assert c.post("/admin/schedule", data={}).status_code == 403
        assert c.get("/schedule").status_code == 200
