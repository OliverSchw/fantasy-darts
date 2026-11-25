"""Bierpong: Live-Spiel, Stats, Turniere mit Teams."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import beerpong as bp
from app import competitors, models
from app import competitors as comp
from app import tournaments as tour
from app.main import app


def _login(name):
    c = TestClient(app)
    c.__enter__()
    c.post("/login", data={"username": name, "password": "secret123"})
    return c


@pytest.fixture
def olli(db, make_user):
    make_user("olli")
    c = _login("olli")
    yield c
    c.__exit__(None, None, None)


def _me(db, name="olli"):
    u = db.scalar(select(models.User).where(models.User.username == name))
    return competitors.competitor_for_user(db, u).id


def _game(olli, db, cups=6):
    r = olli.post("/beerpong/new", data={"cups": cups, "a0": _me(db), "a1": "guest", "ag1": "Kevin",
                                         "b0": "guest", "bg0": "Marco", "b1": "guest", "bg1": "Tim", "n2": "Cup Kings"},
                  follow_redirects=False)
    assert r.status_code == 303, r.text[:400]
    return db.get(models.BeerpongGame, int(r.headers["location"].rsplit("/", 1)[1]))


def _hit(c, g, side, delta=1, db=None):
    r = c.post(f"/beerpong/games/{g.id}/hit", data={"side": side, "delta": delta, "v": g.version})
    if db is not None:
        db.refresh(g)
    return r


def test_live_game(olli, db):
    g = _game(olli, db)
    assert g.team_name(1) == "olli & Kevin" and g.team_name(2) == "Cup Kings"
    assert "🍺 Hit!" in olli.get(f"/beerpong/games/{g.id}").text
    for _ in range(4):
        _hit(olli, g, 2, db=db)
    for _ in range(5):
        _hit(olli, g, 1, db=db)
    assert g.status == "live" and (g.hits1, g.hits2) == (5, 4)
    r = _hit(olli, g, 1, db=db)
    assert g.status == "finished" and g.winner_side == 1 and "Winner: olli &amp; Kevin (6:4)" in r.text
    assert "already over" in _hit(olli, g, 2, db=db).text
    _hit(olli, g, 1, -1, db=db)  # Korrektur öffnet das Spiel wieder
    assert g.status == "live" and g.hits1 == 5 and g.winner_side is None
    _hit(olli, g, 1, db=db)
    stats = bp.compute_stats(db)
    me = stats[_me(db)]
    assert me.games == 1 and me.wins == 1 and me.cups_for == 6 and me.cups_against == 4
    assert len([s for s in stats.values() if s.wins == 0]) == 2  # Marco, Tim


def test_double_tap_and_permissions(olli, db, make_user):
    g = _game(olli, db)
    v = g.version
    olli.post(f"/beerpong/games/{g.id}/hit", data={"side": 1, "delta": 1, "v": v})
    r = olli.post(f"/beerpong/games/{g.id}/hit", data={"side": 1, "delta": 1, "v": v})
    assert "updated in the meantime" in r.text
    db.refresh(g)
    assert g.hits1 == 1
    make_user("anna")
    anna = _login("anna")
    assert anna.post(f"/beerpong/games/{g.id}/hit", data={"side": 1, "delta": 1, "v": g.version}).status_code == 403
    assert "🍺 Hit!" not in anna.get(f"/beerpong/games/{g.id}").text
    assert anna.get(f"/beerpong/games/{g.id}/version").json() == {"v": g.version, "status": "live"}
    with TestClient(app) as guest:
        assert guest.get("/beerpong", follow_redirects=False).status_code == 303


def test_abandon_and_validation(olli, db):
    g = _game(olli, db)
    _hit(olli, g, 1, db=db)
    olli.post(f"/beerpong/games/{g.id}/abandon")
    db.refresh(g)
    assert g.status == "abandoned" and bp.compute_stats(db) == {}
    me = _me(db)
    r = olli.post("/beerpong/new", data={"cups": 6, "a0": me, "b0": me})
    assert r.status_code == 400 and "one side" in r.text
    r = olli.post("/beerpong/new", data={"cups": 8, "a0": me, "b0": "guest", "bg0": "Zoe"})
    assert r.status_code == 400


def test_parse_teams_and_random_pairs(db, make_user):
    make_user("anna")
    teams, names = comp.parse_teams(db, "Cup Kings: Anna, Kevin\nMarco & Tim\n\n Zoe + kevin ")
    assert names == ["Cup Kings", None, None]
    anna = _me(db, "anna")
    assert teams[0][0] == anna and teams[2][1] == teams[0][1]  # "kevin" = derselbe Gast
    assert len({cid for t in teams for cid in t}) == 5
    with pytest.raises(comp.CompetitorError):
        comp.random_pairs([1, 2, 3])
    pairs = comp.random_pairs([1, 2, 3, 4, 5, 6])
    assert len(pairs) == 3 and sorted(x for p in pairs for x in p) == [1, 2, 3, 4, 5, 6]


def test_tournament_flow(olli, db):
    olli.get("/beerpong")
    r = olli.post("/beerpong/tournaments/new", data={
        "name": "Summer Pong", "cups": 6, "mode": "fixed",
        "teams": "Cup Kings: olli, Kevin\nMarco, Tim\nZoe, Lea"}, follow_redirects=False)
    assert r.status_code == 303, r.text[:400]
    t = db.scalar(select(models.Tournament))
    assert t.sport == "beerpong" and len(t.entries) == 3 and t.entries[0].display_name == "Cup Kings"
    assert "Semi-finals" in olli.get(f"/beerpong/tournaments/{t.id}").text
    assert olli.get(f"/darts/tournaments/{t.id}").status_code == 404  # anderer Bereich

    semi = next(m for m in t.matches if m.round == 1 and not m.bye)
    final = next(m for m in t.matches if m.round == 2)
    r = olli.post(f"/beerpong/tournaments/{t.id}/matches/{semi.id}/play", follow_redirects=False)
    g = db.get(models.BeerpongGame, int(r.headers["location"].rsplit("/", 1)[1]))
    assert g.tournament_match_id == semi.id and g.cups == 6
    assert "Summer Pong" in olli.get(f"/beerpong/games/{g.id}").text
    for _ in range(6):
        _hit(olli, g, 2, db=db)
    db.expire_all()
    semi = db.get(models.TournamentMatch, semi.id)
    assert semi.is_played and (semi.score1, semi.score2) == (0, 6)
    final = db.get(models.TournamentMatch, final.id)
    assert final.entry2_id == semi.entry2_id

    # Finale per Hand: Gewinner muss alle Becher treffen
    r = olli.post(f"/beerpong/tournaments/{t.id}/matches/{final.id}/result", data={"score1": 4, "score2": 5})
    assert "hits all 6 cups" in r.text
    olli.post(f"/beerpong/tournaments/{t.id}/matches/{final.id}/result", data={"score1": 6, "score2": 2})
    db.expire_all()
    t = db.get(models.Tournament, t.id)
    assert t.status == "finished" and tour.entry_by_id(t, t.winner_entry_id).display_name == "Cup Kings"
    assert bp.compute_stats(db)[_me(db)].wins == 1  # das Final-Spiel zählt für die Stats

    # -1 im Halbfinal-Spiel ist gesperrt, solange das Finale ein Ergebnis hat
    db.refresh(g)
    assert "reset that one first" in _hit(olli, g, 2, -1).text
    olli.post(f"/beerpong/tournaments/{t.id}/matches/{final.id}/reset")
    db.expire_all()
    assert not db.get(models.TournamentMatch, final.id).is_played
    final_game = db.scalar(select(models.BeerpongGame).where(models.BeerpongGame.tournament_match_id == final.id))
    assert final_game.status == "abandoned"
    for url in ("/beerpong", "/beerpong/stats", "/beerpong/tournaments", "/beerpong/tournaments/new",
                f"/beerpong/tournaments/{t.id}/matches/{final.id}", "/"):
        assert olli.get(url).status_code == 200, url


def test_random_tournament_needs_even(olli, db):
    r = olli.post("/beerpong/tournaments/new", data={"name": "X", "cups": 10, "mode": "random", "guests": "A, B, C"})
    assert r.status_code == 400 and "even number" in r.text
    r = olli.post("/beerpong/tournaments/new", data={"name": "X", "cups": 10, "mode": "random",
                                                     "guests": "A, B, C, D", "shuffle": "1"}, follow_redirects=False)
    assert r.status_code == 303
    t = db.scalar(select(models.Tournament))
    assert len(t.entries) == 2 and all(len(e.members) == 2 for e in t.entries)


def test_group_tournament(olli, db):
    r = olli.post("/beerpong/tournaments/new", data={
        "name": "Pong Groups", "cups": 6, "mode": "fixed", "format": "groups", "groups": 2, "advance": 1,
        "teams": "T1: a1, a2\nT2: b1, b2\nT3: c1, c2\nT4: d1, d2"}, follow_redirects=False)
    assert r.status_code == 303, r.text[:400]
    t = db.scalar(select(models.Tournament))
    assert t.has_groups and len(t.group_matches) == 2
    for m in t.group_matches:
        olli.post(f"/beerpong/tournaments/{t.id}/matches/{m.id}/result", data={"score1": 6, "score2": 3})
    db.expire_all()
    t = db.get(models.Tournament, t.id)
    assert tour.knockout_started(t) and t.num_rounds == 1  # 2 Gruppensieger -> Finale
    final = t.ko_matches[0]
    assert {final.entry1_id, final.entry2_id} == {m.winner_id for m in t.group_matches}
    page = olli.get(f"/beerpong/tournaments/{t.id}").text
    assert "Group A" in page and "Final" in page
    # Gruppenspiele zählen für die Stats (je ein Spiel pro Ergebnis)
    assert sum(s.games for s in bp.compute_stats(db).values()) == 8
