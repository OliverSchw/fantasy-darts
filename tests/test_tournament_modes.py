"""Darts-Turniere im Doppel und mit Partyspielen, TV-Ansicht."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app import tournaments as tour
from app.darts import service
from app.main import app


@pytest.fixture
def olli(db, make_user):
    make_user("olli")
    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        yield c


def _create(c, **data):
    base = {"name": "Cup", "start": 301, "legs": 1, "final_legs": 1}
    r = c.post("/darts/tournaments/new", data={**base, **data}, follow_redirects=False)
    assert r.status_code == 303, r.text[:500]
    return int(r.headers["location"].rsplit("/", 1)[1])


def test_doubles_tournament_random_pairs(olli, db):
    tid = _create(olli, teams="random", guests="A, B, C, D, E, F, G, H", boards=2)
    t = db.get(models.Tournament, tid)
    assert len(t.entries) == 4 and all(len(e.members) == 2 for e in t.entries)
    assert "doubles" in olli.get(f"/darts/tournaments/{tid}").text
    semi = next(m for m in t.ko_matches if m.round == 1)
    r = olli.post(f"/darts/tournaments/{tid}/matches/{semi.id}/play", follow_redirects=False)
    g = db.get(models.DartsGame, int(r.headers["location"].rsplit("/", 1)[1]))
    a = [m.competitor_id for m in semi.entry1.members]
    b = [m.competitor_id for m in semi.entry2.members]
    assert g.team_size == 2 and [p.competitor_id for p in g.players] == [a[0], b[0], a[1], b[1]]
    # T1 gewinnt: 180 (121), 0, 81 (40), 0, 40 Checkout
    for score, darts in ((180, None), (0, None), (81, None), (0, None), (40, 2)):
        service.add_visit(db, g, score, darts, len(g.visits))
    db.expire_all()
    semi = db.get(models.TournamentMatch, semi.id)
    assert semi.is_played and semi.winner_id == semi.entry1_id and (semi.score1, semi.score2) == (1, 0)


def test_fixed_teams_validation(olli, db):
    r = olli.post("/darts/tournaments/new", data={"name": "X", "start": 301, "legs": 1, "final_legs": 1,
                                                  "teams": "fixed", "team_text": "A: a1, a2\nB: b1"})
    assert r.status_code == 400 and "exactly 2 players" in r.text
    tid = _create(olli, teams="fixed", team_text="Arrows: p1, p2\np3, p4")
    t = db.get(models.Tournament, tid)
    assert t.entries[0].display_name in ("Arrows", "p3 & p4") and len(t.entries) == 2
    r = olli.post("/darts/tournaments/new", data={"name": "X", "mode": "cricket", "teams": "random", "guests": "a,b,c,d"})
    assert r.status_code == 400 and "played in X01" in r.text


def test_cricket_tournament(olli, db):
    tid = _create(olli, mode="cricket", guests="C1, C2, C3, C4")
    t = db.get(models.Tournament, tid)
    assert t.settings["mode"] == "cricket" and t.settings["legs"] == 1
    assert "Cricket" in olli.get(f"/darts/tournaments/{tid}").text
    s1, s2 = sorted((m for m in t.ko_matches if m.round == 1), key=lambda m: m.slot)
    r = olli.post(f"/darts/tournaments/{tid}/matches/{s1.id}/play", follow_redirects=False)
    g = db.get(models.DartsGame, int(r.headers["location"].rsplit("/", 1)[1]))
    assert g.mode == "cricket" and g.tournament_match_id == s1.id
    for tgt in ("T20", "T19", "T18", "T17", "T16", "T15"):
        service.add_mode_visit(db, g, [tgt, "M", "M"], len(g.visits))
        service.add_mode_visit(db, g, ["M", "M", "M"], len(g.visits))
    service.add_mode_visit(db, g, ["DB", "SB"], len(g.visits))  # Seite 0 (Eintrag 1) gewinnt
    db.expire_all()
    s1 = db.get(models.TournamentMatch, s1.id)
    assert s1.is_played and s1.winner_id == s1.entry1_id and (s1.score1, s1.score2) == (1, 0)
    # Ergebnis von Hand: nur 1:0 / 0:1
    r = olli.post(f"/darts/tournaments/{tid}/matches/{s2.id}/result", data={"score1": 3, "score2": 1})
    assert "Enter 1 for the winner" in r.text
    olli.post(f"/darts/tournaments/{tid}/matches/{s2.id}/result", data={"score1": 0, "score2": 1})
    db.expire_all()
    final = next(m for m in db.get(models.Tournament, tid).ko_matches if m.round == 2)
    assert final.entry1_id and final.entry2_id
    # Undo der Entscheidung im Halbfinale geht nicht mehr? Doch: Finale noch offen -> Reset erlaubt
    g = db.get(models.DartsGame, g.id)
    assert service.undo_last(db, g)
    db.expire_all()
    assert not db.get(models.TournamentMatch, s1.id).is_played


def test_tv_view(olli, db):
    tid = _create(olli, guests="T1, T2, T3, T4", boards=2)
    t = db.get(models.Tournament, tid)
    on = next(m for m in t.matches if m.board == 1)
    r = olli.post(f"/darts/tournaments/{tid}/matches/{on.id}/play", follow_redirects=False)
    g = db.get(models.DartsGame, int(r.headers["location"].rsplit("/", 1)[1]))
    service.add_visit(db, g, 100, None, 0)
    page = olli.get(f"/darts/tournaments/{tid}/tv").text
    assert "Board 1" in page and "Board 2" in page and "LIVE" in page and "201 : 301" in page
    inner = olli.get(f"/darts/tournaments/{tid}/tv?partial=1").text
    assert "<html" not in inner and "201 : 301" in inner
    assert "📺 TV view" in olli.get(f"/darts/tournaments/{tid}").text
    olli.post("/beerpong/tournaments/new", data={"name": "P", "cups": 6, "mode": "fixed", "boards": 1,
                                                 "teams": "A: a1, a2\nB: b1, b2"})
    bt = db.scalars(select(models.Tournament).where(models.Tournament.sport == "beerpong")).first()
    assert "Table 1" in olli.get(f"/beerpong/tournaments/{bt.id}/tv").text
    with TestClient(app) as guest:
        assert guest.get(f"/darts/tournaments/{tid}/tv", follow_redirects=False).status_code == 303
