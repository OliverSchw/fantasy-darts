"""End-to-end über HTTP: Login, Team bauen, Sperren, Ergebnis eintragen, Ranking."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.main import app
from app.season import season_players


@pytest.fixture
def client(db):
    with TestClient(app) as c:
        yield c


def _login(client, name, pw="secret123"):
    r = client.post("/login", data={"username": name, "password": pw}, follow_redirects=False)
    assert r.status_code == 303, r.text


def _team_form(db, season, rules, name="Bullseye"):
    cheap = sorted(season_players(db, season).values(), key=lambda p: p.price)[: rules.team.squad_size]
    ids = [p.id for p in cheap]
    return {"name": name, "player_ids": ids, "playmaker_id": ids[-1], "underdog_id": ids[0], "champion_pick_id": ids[0]}


def test_public_pages_render(client):
    for url in ("/", "/fantasy", "/fantasy/players", "/fantasy/bracket", "/fantasy/bracket?round=7", "/fantasy/rules", "/login", "/manifest.webmanifest", "/sw.js"):
        assert client.get(url).status_code == 200, url


def test_protected_pages_redirect_to_login(client):
    r = client.get("/fantasy/my", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert client.post("/fantasy/my/new", data={}, follow_redirects=False).status_code == 303


def test_wrong_password(client, make_user):
    make_user("olli")
    r = client.post("/login", data={"username": "olli", "password": "nope"})
    assert r.status_code == 401


def test_full_flow(client, db, season, rules, make_user):
    make_user("olli")
    make_user("boss", admin=True)
    _login(client, "olli")

    # Ungültiges Team -> 400 mit Fehlermeldungen
    r = client.post("/fantasy/my/new", data={"name": "X", "player_ids": [1, 2]})
    assert r.status_code == 400 and "Select exactly" in r.text

    form = _team_form(db, season, rules)
    r = client.post("/fantasy/my/new", data=form, follow_redirects=False)
    assert r.status_code == 303
    team = db.scalar(select(models.Team))
    assert team.is_active and len(team.player_ids) == rules.team.squad_size

    # Name doppelt
    assert client.post("/fantasy/my/new", data=form).status_code == 400

    assert "Bullseye" in client.get("/fantasy").text
    assert client.get(f"/fantasy/teams/{team.id}").status_code == 200

    # Normale User dürfen keine Ergebnisse eintragen
    m = db.scalar(select(models.Match).where(models.Match.round == 1, models.Match.p1_id == form["underdog_id"]))
    if m is None:
        m = db.scalar(select(models.Match).where(models.Match.round == 1, models.Match.p2_id == form["underdog_id"]))
    assert client.post(f"/fantasy/bracket/match/{m.id}", data={"sets_p1": 3, "sets_p2": 0}).status_code == 403

    # Admin sperrt und trägt Ergebnis ein
    client.post("/logout")
    _login(client, "boss")
    client.post("/fantasy/admin/lock", data={"locked": "true"})
    winner_is_p1 = m.p1_id == form["underdog_id"]
    r = client.post(f"/fantasy/bracket/match/{m.id}",
                    data={"sets_p1": 3 if winner_is_p1 else 1, "sets_p2": 1 if winner_is_p1 else 3, "p1_s171": 2, "p2_s171": 2},
                    follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert db.get(models.Match, m.id).winner_id == form["underdog_id"]

    # Fremdes Team jetzt sichtbar, Ranking zeigt Punkte:
    # Underdog gewinnt 3-1: 30 + 20 + 2 (171er) = 52, x2 als Underdog = 104
    assert client.get(f"/fantasy/teams/{team.id}").status_code == 200
    assert ">104<" in client.get("/fantasy").text

    # Nach dem Sperren keine Änderungen mehr
    client.post("/logout")
    _login(client, "olli")
    r = client.post(f"/fantasy/my/{team.id}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert db.get(models.Team, team.id) is not None


def test_other_teams_hidden_before_lock(client, db, season, rules, make_user):
    make_user("olli")
    make_user("anna")
    _login(client, "olli")
    client.post("/fantasy/my/new", data=_team_form(db, season, rules))
    team_id = db.scalar(select(models.Team.id))
    client.post("/logout")
    _login(client, "anna")
    assert client.get(f"/fantasy/teams/{team_id}").status_code == 403
    assert client.post(f"/fantasy/my/{team_id}/delete").status_code == 404
