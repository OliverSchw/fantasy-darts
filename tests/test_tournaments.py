"""K.-o.-Turniere: Setzliste, Freilose, Weiterrücken, Darts-Anbindung."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app import tournaments as tour
from app.darts import service
from app.main import app


def _guests(db, n):
    return [service.create_guest(db, f"Player {i}").id for i in range(1, n + 1)]


def _t(db, n, **kw):
    return tour.create_tournament(db, "darts", "Cup", [[c] for c in _guests(db, n)], {"start": 301, "legs": 1}, None, **kw)


def _m(t, r, s):
    return next(m for m in t.matches if m.round == r and m.slot == s)


def _seed(t, entry_id):
    return tour.entry_by_id(t, entry_id).seed if entry_id else None


def test_bracket_order():
    assert tour.bracket_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]
    assert tour.round_title(3, 3) == "Final" and tour.round_title(1, 3) == "Quarter-finals"
    assert tour.round_title(1, 5) == "Round of 32"


@pytest.mark.parametrize("n,byes", [(2, 0), (3, 1), (5, 3), (8, 0), (6, 2)])
def test_byes_go_to_top_seeds(db, n, byes):
    t = _t(db, n)
    bye_matches = [m for m in t.matches if m.bye]
    assert len(bye_matches) == byes
    assert sorted(_seed(t, m.winner_id) for m in bye_matches) == list(range(1, byes + 1))
    size = 1 << (t.num_rounds)
    assert len([m for m in t.matches if m.round == 1]) == size // 2


def test_results_advance_and_finish(db):
    t = _t(db, 3)  # 1 hat Freilos; 2 gegen 3
    final = _m(t, 2, 0)
    assert _seed(t, final.entry1_id) == 1 and final.entry2_id is None
    semi = _m(t, 1, 1)
    tour.set_result(db, t, semi, 0, 1)  # Seed 3 gewinnt
    assert _seed(t, final.entry2_id) == 3
    with pytest.raises(tour.TournamentError):
        tour.set_result(db, t, final, 1, 1)  # kein Unentschieden
    tour.set_result(db, t, final, 2, 1)
    assert t.status == "finished" and _seed(t, t.winner_entry_id) == 1
    # Halbfinale nicht mehr änderbar, weil das Finale ein Ergebnis hat
    assert not tour.can_change(t, semi)
    with pytest.raises(tour.TournamentError):
        tour.clear_result(db, t, semi)
    tour.clear_result(db, t, final)
    assert t.status == "running" and t.winner_entry_id is None
    tour.clear_result(db, t, semi)
    assert final.entry2_id is None


def test_validation(db):
    ids = _guests(db, 2)
    with pytest.raises(tour.TournamentError):
        tour.create_tournament(db, "darts", "Cup", [[ids[0]]], {}, None)
    with pytest.raises(tour.TournamentError):
        tour.create_tournament(db, "darts", "Cup", [[ids[0]], [ids[0]]], {}, None)
    with pytest.raises(tour.TournamentError):
        tour.create_tournament(db, "darts", " ", [[ids[0]], [ids[1]]], {}, None)


# ---------------------------------------------------------------- über die Webseite


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


def _play_out(c, db, game, winner_first=True):
    """301, first to 1: der jeweilige Spieler wirft 180, 81, 40 (Checkout)."""
    db.refresh(game)
    loser_scores = iter([0, 0, 0])
    me = 0 if winner_first else 1
    while game.status == "live":
        st = service.game_state(game)
        if st.turn == me:
            rest = st.remaining[me]
            score = 180 if rest == 301 else (81 if rest == 121 else 40)
            data = {"score": score, "seq": len(game.visits)}
            if score == rest:
                data["darts"] = 1
        else:
            data = {"score": next(loser_scores), "seq": len(game.visits)}
        c.post(f"/darts/games/{game.id}/visit", data=data)
        db.refresh(game)


def test_darts_tournament_flow(olli, db, make_user):
    make_user("anna")
    olli.get("/darts")
    r = olli.post("/darts/tournaments/new", data={"name": "Xmas Cup", "start": 301, "legs": 1, "final_legs": 1,
                                                  "players": [], "guests": "Kevin, Marco\nTim"},
                  follow_redirects=False)
    assert r.status_code == 303, r.text[:400]
    t = db.scalar(select(models.Tournament))
    assert t.name == "Xmas Cup" and len(t.entries) == 3 and t.num_rounds == 2
    page = olli.get(f"/darts/tournaments/{t.id}").text
    assert "Semi-finals" in page and "Final" in page and "bye" in page

    semi = next(m for m in t.matches if m.round == 1 and not m.bye)
    r = olli.post(f"/darts/tournaments/{t.id}/matches/{semi.id}/play", follow_redirects=False)
    game = db.get(models.DartsGame, int(r.headers["location"].rsplit("/", 1)[1]))
    assert game.tournament_match_id == semi.id and game.legs_to_win == 1
    assert "Xmas Cup" in olli.get(f"/darts/games/{game.id}").text
    # Nochmal "Play" öffnet dasselbe laufende Spiel
    r2 = olli.post(f"/darts/tournaments/{t.id}/matches/{semi.id}/play", follow_redirects=False)
    assert r2.headers["location"] == r.headers["location"]

    _play_out(olli, db, game, winner_first=True)
    db.expire_all()
    semi = db.get(models.TournamentMatch, semi.id)
    final = next(m for m in db.get(models.Tournament, t.id).matches if m.round == 2)
    assert semi.is_played and semi.score1 == 1 and semi.score2 == 0
    assert final.entry1_id and final.entry2_id == semi.entry1_id

    # Finale per Hand eintragen
    olli.post(f"/darts/tournaments/{t.id}/matches/{final.id}/result", data={"score1": 0, "score2": 1})
    db.expire_all()
    t = db.get(models.Tournament, t.id)
    assert t.status == "finished" and t.winner_entry_id == semi.entry1_id
    assert "wins the tournament" in olli.get(f"/darts/tournaments/{t.id}").text

    # Undo im Halbfinal-Spiel ist gesperrt, solange das Finale ein Ergebnis hat
    r = olli.post(f"/darts/games/{game.id}/undo")
    assert "reset that one first" in r.text
    db.refresh(game)
    assert game.status == "finished"
    # Finale zurücksetzen -> Undo geht und öffnet das Halbfinale wieder
    olli.post(f"/darts/tournaments/{t.id}/matches/{final.id}/reset")
    olli.post(f"/darts/games/{game.id}/undo")
    db.expire_all()
    assert db.get(models.DartsGame, game.id).status == "live"
    assert not db.get(models.TournamentMatch, semi.id).is_played

    # Rechte: anna organisiert nicht
    anna = _login("anna")
    assert anna.post(f"/darts/tournaments/{t.id}/matches/{final.id}/result", data={"score1": 1, "score2": 0}).status_code == 403
    assert anna.post(f"/darts/tournaments/{t.id}/delete").status_code == 403
    assert anna.post(f"/darts/tournaments/{t.id}/matches/{semi.id}/play").status_code == 403
    for url in ("/darts/tournaments", f"/darts/tournaments/{t.id}", f"/darts/tournaments/{t.id}/matches/{final.id}"):
        assert anna.get(url).status_code == 200, url

    # Löschen: Spiele bleiben im Verlauf
    olli.post(f"/darts/tournaments/{t.id}/delete")
    db.expire_all()
    assert db.scalar(select(models.Tournament)) is None
    assert db.get(models.DartsGame, game.id) is not None
    assert olli.get(f"/darts/games/{game.id}").status_code == 200


def test_new_tournament_validation(olli, db):
    r = olli.post("/darts/tournaments/new", data={"name": "Solo", "start": 501, "legs": 2, "final_legs": 3,
                                                  "guests": "Kevin"})
    assert r.status_code == 400 and "2 to 64" in r.text
    assert db.scalar(select(models.Tournament)) is None
