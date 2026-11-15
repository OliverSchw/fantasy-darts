"""Baum-Ansicht, Spielerstatus, Ranking-Bewegung, Insights, Team kopieren, Registrierung."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.bracket import save_result
from app.bracket_view import Bracket
from app.main import app
from app.season import season_matches, season_players
from app.settings import get_settings
from app.teams import TeamInput, save_team


def _m(db, season, rnd, slot):
    return db.scalar(select(models.Match).where(
        models.Match.season_id == season.id, models.Match.round == rnd, models.Match.slot == slot))


def _bracket(db, season, rules):
    return Bracket(rules, season_matches(db, season), season_players(db, season))


def test_sections_cover_whole_tree(db, season, rules):
    sections = _bracket(db, season, rules).sections()
    assert len(sections) == 9 and sections[-1].key == "finals"
    assert sections[0].label == "Littler"  # nach dem Top-Seed benannt
    # Achtel: 8 + 4 + 2 + 1 Matches, Finals: 4 + 2 + 1 + Champion-Spalte
    assert [sum(len(g) for g in c.groups) for c in sections[0].columns] == [8, 4, 2, 1]
    assert [sum(len(g) for g in c.groups) for c in sections[-1].columns] == [4, 2, 1, 0]
    total = sum(sum(len(g) for g in c.groups) for s in sections for c in s.columns)
    assert total == 127


def test_candidates_and_status(db, season, rules):
    m0, m1 = _m(db, season, 1, 0), _m(db, season, 1, 1)
    br = _bracket(db, season, rules)
    r2 = br.by_pos[(2, 0)]
    side = br.side(r2, 0)
    assert side.pid is None and set(side.candidates) == {m0.p1_id, m0.p2_id}

    save_result(db, rules, m0, 3, 0, {}, {})
    br = _bracket(db, season, rules)
    winner, loser = m0.p1_id, m0.p2_id
    assert br.status(loser).state == "out" and br.status(loser).round_no == 1
    st = br.status(winner)
    assert st.state == "alive" and st.round_no == 2
    assert set(st.opponent.candidates) == {m1.p1_id, m1.p2_id}
    assert br.section_of(winner) == "1"


def test_leaderboard_movement(db, season, rules, make_user):
    from app.web.common import State

    players = season_players(db, season)
    r1 = [_m(db, season, 1, s) for s in range(4)]
    users = [make_user("a"), make_user("b")]
    # Team A hat Spieler aus Match 0, Team B aus Match 1 (Rest: billige Füller)
    fill = [p.id for p in sorted(players.values(), key=lambda p: p.price)
            if p.id not in {m.p1_id for m in r1} | {m.p2_id for m in r1}]
    for u, m, extra in ((users[0], r1[0], fill[:14]), (users[1], r1[1], fill[14:28])):
        ids = [m.p1_id] + extra
        save_team(db, models.Team(season_id=season.id, user_id=u.id),
                  TeamInput(f"T{u.username}", ids, extra[0], extra[0], extra[0]))

    save_result(db, rules, r1[0], 3, 0, {}, {})  # gestern: A vorne
    r1[0].updated_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    save_result(db, rules, r1[1], 3, 0, {"s171": 5}, {})  # heute: B zieht vorbei

    state = State(db=db, season=season, rules=rules, user=None)
    rows = state.leaderboard()
    assert [r["team"].name for r in rows] == ["Tb", "Ta"]
    assert rows[0]["move"] == 1 and rows[1]["move"] == -1


@pytest.fixture
def client(db):
    with TestClient(app) as c:
        yield c


def _login(client, name):
    assert client.post("/login", data={"username": name, "password": "secret123"},
                       follow_redirects=False).status_code == 303


def _team_form(db, season, rules, name):
    cheap = sorted(season_players(db, season).values(), key=lambda p: p.price)[: rules.team.squad_size]
    ids = [p.id for p in cheap]
    return {"name": name, "player_ids": ids, "playmaker_id": ids[-1], "underdog_id": ids[0], "champion_pick_id": ids[0]}


def test_pages_with_results(client, db, season, rules, make_user):
    make_user("olli")
    _login(client, "olli")
    form = _team_form(db, season, rules, "Bulls")
    client.post("/my/new", data=form)
    m = _m(db, season, 1, 0)
    save_result(db, rules, m, 3, 1, {"s171": 2}, {})

    for url in ("/bracket", "/bracket?section=3", "/bracket?section=finals", "/bracket?view=list&round=2",
                f"/players/{m.p1_id}", f"/players/{m.p2_id}", "/"):
        r = client.get(url)
        assert r.status_code == 200, url
    assert "win margin +2" in client.get(f"/players/{m.p1_id}").text
    assert "Latest results" in client.get("/").text

    # Insights erst nach dem Sperren
    assert client.get("/insights").status_code == 403
    season.teams_locked = True
    db.commit()
    r = client.get("/insights")
    assert r.status_code == 200 and "Champion picks" in r.text


def test_copy_team(client, db, season, rules, make_user):
    make_user("olli")
    _login(client, "olli")
    client.post("/my/new", data=_team_form(db, season, rules, "Original"))
    team = db.scalar(select(models.Team))
    r = client.get(f"/my/new?copy={team.id}")
    assert r.status_code == 200 and "Original (copy)" in r.text
    assert client.get("/my/new?copy=9999").status_code == 404


def test_register_with_invite_code(client, db, monkeypatch):
    assert client.get("/register").status_code == 404  # ohne Code deaktiviert
    monkeypatch.setattr(get_settings(), "invite_code", "darts")
    assert client.post("/register", data={"username": "neu", "password": "secret123", "code": "falsch"}).status_code == 400
    r = client.post("/register", data={"username": "neu", "password": "secret123", "code": "darts"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert db.scalar(select(models.User).where(models.User.username == "neu")) is not None
    assert client.get("/my").status_code == 200  # direkt eingeloggt


def test_compare_teams(client, db, season, rules, make_user):
    make_user("olli")
    _login(client, "olli")
    assert client.get("/compare").status_code == 200  # nur 1 Team -> Hinweis statt Vergleich
    assert "Build a second team" in client.get("/compare").text

    client.post("/my/new", data=_team_form(db, season, rules, "Eins"))
    form = _team_form(db, season, rules, "Zwei")
    next_cheapest = sorted(season_players(db, season).values(), key=lambda p: p.price)[rules.team.squad_size]
    form["player_ids"] = [form["player_ids"][0], next_cheapest.id] + form["player_ids"][2:]
    assert client.post("/my/new", data=form, follow_redirects=False).status_code == 303
    t1, t2 = db.scalars(select(models.Team).order_by(models.Team.id)).all()

    r = client.get(f"/compare?a={t1.id}&b={t2.id}")
    assert r.status_code == 200
    assert "Shared players (14)" in r.text and "Different players (1)" in r.text

    # Fremde Teams vor dem Sperren nicht vergleichbar
    make_user("anna")
    client.post("/logout")
    _login(client, "anna")
    r = client.get(f"/compare?a={t1.id}&b={t2.id}")
    assert "Eins" not in r.text and "Zwei" not in r.text
    client.post("/my/new", data=_team_form(db, season, rules, "Annas"))
    client.post("/my/new", data={**_team_form(db, season, rules, "Annas2")})
    assert client.get(f"/compare?a={t1.id}&b={t2.id}").status_code == 404


def test_player_page_lists_own_teams_before_lock(client, db, season, rules, make_user):
    make_user("olli")
    _login(client, "olli")
    form = _team_form(db, season, rules, "Meins")
    client.post("/my/new", data=form)
    r = client.get(f"/players/{form['player_ids'][0]}")
    assert "In your teams" in r.text and "Meins" in r.text
