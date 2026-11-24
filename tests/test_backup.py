import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import models
from app.backup import export_backup, restore_backup
from app.bracket import save_result
from app.db import Base
from app.main import app
from app.scoring import player_scores, team_score
from app.season import season_matches, season_players
from app.settings import Settings, get_settings
from app.teams import TeamInput, save_team


def _setup(db, season, rules, make_user):
    u = make_user("olli")
    ids = [p.id for p in sorted(season_players(db, season).values(), key=lambda p: p.price)[:15]]
    save_team(db, models.Team(season_id=season.id, user_id=u.id), TeamInput("Bulls", ids, ids[-1], ids[0], ids[0]))
    m = db.scalar(select(models.Match).where(models.Match.round == 1, models.Match.slot == 0))
    save_result(db, rules, m, 3, 1, {"s171": 2}, {"f161": 1})
    return u


def _total(db, season, rules):
    scores = player_scores(rules, season_matches(db, season))
    return {t.name: team_score(rules, t, scores).total
            for t in db.scalars(select(models.Team).where(models.Team.season_id == season.id))}


def test_backup_roundtrip_into_fresh_db(db, season, rules, make_user, tmp_path):
    _setup(db, season, rules, make_user)
    data = json.loads(json.dumps(export_backup(db, season)))  # wie beim Speichern als Datei

    engine = create_engine(f"sqlite:///{tmp_path / 'restore.db'}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as fresh:
        restored = restore_backup(fresh, data)
        assert _total(fresh, restored, rules) == _total(db, season, rules)
        assert fresh.scalar(select(models.User).where(models.User.username == "olli")).password_hash \
            == data["users"][0]["password_hash"]
        with pytest.raises(ValueError):  # zweimal einspielen geht nicht
            restore_backup(fresh, data)


def test_admin_exports(db, season, rules, make_user):
    _setup(db, season, rules, make_user)
    make_user("boss", admin=True)
    with TestClient(app) as c:
        assert c.get("/fantasy/admin/export/teams", follow_redirects=False).status_code == 303  # nicht eingeloggt
        c.post("/login", data={"username": "olli", "password": "secret123"})
        assert c.get("/fantasy/admin/export/teams").status_code == 403  # kein Admin
        c.post("/logout")
        c.post("/login", data={"username": "boss", "password": "secret123"})

        r = c.get("/fantasy/admin/export/teams")
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
        assert "Bulls;olli;yes" in r.text
        r = c.get("/fantasy/admin/export/results")
        assert r.text.count("\n") == 2 and "Round 1;1;" in r.text  # Kopf + 1 Ergebnis
        assert c.get("/fantasy/admin/export/players").status_code == 200
        backup = c.get("/fantasy/admin/export/backup").json()
        assert backup["season"]["key"] == "wm2026" and len(backup["teams"]) == 1
        assert c.get("/fantasy/admin/export/nope").status_code == 404


def test_sqlite_refused_on_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///x.db")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            get_settings()
    finally:
        monkeypatch.delenv("VERCEL")
        monkeypatch.undo()
        get_settings.cache_clear()
    assert isinstance(get_settings(), Settings)


def test_backup_includes_invites(db, season, make_user, tmp_path):
    from datetime import datetime, timezone

    olli = make_user("olli")
    db.add_all([models.Invite(token="offen123", note="Anna"),
                models.Invite(token="benutzt1", note="Olli", used_by_id=olli.id, used_at=datetime.now(timezone.utc))])
    db.commit()
    data = json.loads(json.dumps(export_backup(db, season)))
    assert {i["token"] for i in data["invites"]} == {"offen123", "benutzt1"}

    engine = create_engine(f"sqlite:///{tmp_path / 'restore.db'}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as fresh:
        restore_backup(fresh, data)
        invites = {i.token: i for i in fresh.scalars(select(models.Invite))}
        assert invites["offen123"].used_at is None and invites["offen123"].note == "Anna"
        used = invites["benutzt1"]
        assert used.used_at is not None and fresh.get(models.User, used.used_by_id).username == "olli"

    # Ältere Backups ohne "invites" lassen sich weiter einspielen
    del data["invites"]
    data["season"]["key"] = season.key
    engine2 = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(engine2)
    with sessionmaker(bind=engine2, expire_on_commit=False)() as fresh:
        restore_backup(fresh, data)
        assert fresh.scalar(select(models.Invite)) is None


def test_backup_includes_avatars(db, season, make_user, tmp_path):
    from app.avatars import save_avatar
    from io import BytesIO
    from PIL import Image

    olli = make_user("olli")
    buf = BytesIO(); Image.new("RGB", (50, 50), (0, 128, 0)).save(buf, "PNG")
    save_avatar(db, olli, buf.getvalue())
    data = json.loads(json.dumps(export_backup(db, season)))

    engine = create_engine(f"sqlite:///{tmp_path / 'restore.db'}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as fresh:
        restore_backup(fresh, data)
        u = fresh.scalar(select(models.User).where(models.User.username == "olli"))
        assert u.avatar_version and fresh.get(models.Avatar, u.id).image == db.get(models.Avatar, olli.id).image


def test_backup_includes_games_and_tournaments(db, season, make_user, tmp_path):
    from app import beerpong as bp
    from app import competitors as comp
    from app import tournaments as tour
    from app.darts import service as ds
    from app.darts.stats import compute_stats

    olli = make_user("olli")
    me = comp.competitor_for_user(db, olli)
    kevin = comp.create_guest(db, "Kevin")
    g = ds.create_game(db, 301, 1, [me.id, kevin.id], olli)
    for score, darts in ((180, None), (60, None), (121, 3)):
        ds.add_visit(db, g, score, darts, len(g.visits))
    b = bp.create_game(db, 6, [me.id], [kevin.id], olli, names=("Olli FC", None))
    for _ in range(6):
        bp.add_hit(db, b, 1, 1, b.version)
    ids = [comp.create_guest(db, f"G{i}").id for i in range(4)]
    t = tour.create_tournament(db, "darts", "Cup", [[i] for i in ids], {"start": 301, "legs": 1}, olli, groups=1, advance=2)
    for m in t.group_matches:
        tour.set_result(db, t, m, 1, 0)
    assert tour.knockout_started(t)

    data = json.loads(json.dumps(export_backup(db, season)))
    assert len(data["platform"]["darts_games"]) == 1 and len(data["platform"]["tournaments"]) == 1

    engine = create_engine(f"sqlite:///{tmp_path / 'restore.db'}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as fresh:
        restore_backup(fresh, data)
        new_me = fresh.scalar(select(models.Competitor).where(models.Competitor.user_id.is_not(None)))
        assert compute_stats(fresh)[new_me.id].high_finish == 121
        assert fresh.scalar(select(models.BeerpongGame)).team_name(1) == "Olli FC"
        nt = fresh.scalar(select(models.Tournament))
        old_table = [(s.entry.display_name, s.won) for s in tour.standings(t)[0]]
        assert [(s.entry.display_name, s.won) for s in tour.standings(nt)[0]] == old_table
        assert tour.knockout_started(nt) and len(nt.ko_matches) == 1
        # zweimal einspielen (andere Saison) dupliziert die Spieldaten nicht
        assert not __import__("app.backup", fromlist=["restore_platform"]).restore_platform(
            fresh, data["platform"], {})
