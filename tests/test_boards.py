"""Scheiben/Tische: automatische Zuordnung - Simulation vieler Turniere mit Invarianten-Prüfung."""

import random

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import competitors, models
from app import tournaments as tour
from app.main import app


def _new(db, n, boards, groups=None, advance=2, tag=""):
    ids = [competitors.create_guest(db, f"S{tag}-{i}").id for i in range(n)]
    return tour.create_tournament(db, "darts", "Sim", [[c] for c in ids], {"start": 301, "legs": 1, "boards": boards},
                                  None, groups=groups, advance=advance)


def _check(t):
    n = tour.board_count(t)
    active = [m for m in t.matches if m.board is not None and tour._playable(m)]
    boards = [m.board for m in active]
    assert len(boards) == len(set(boards)), "two open matches on one board"
    assert all(1 <= b <= n for b in boards), "board number out of range"
    people = [e for m in active for e in (m.entry1_id, m.entry2_id)]
    assert len(people) == len(set(people)), "someone plays on two boards"
    busy = set(people)
    waiting = [m for m in t.matches if m.board is None and tour._playable(m)
               and m.entry1_id not in busy and m.entry2_id not in busy]
    if len(active) < n:
        assert not waiting, "free board although a match could start"
    return active


def _simulate(db, t, rng, resets=True, change_boards=True):
    steps = 0
    while t.status == "running":
        steps += 1
        assert steps < 500, "tournament never finishes"
        active = _check(t)
        assert active, "deadlock: nothing on a board but tournament not finished"
        m = rng.choice(active)
        tour.set_result(db, t, m, *((1, 0) if rng.random() < 0.5 else (0, 1)))
        if resets and rng.random() < 0.15:
            played = [x for x in t.matches if x.is_played and tour.can_change(t, x)]
            if played:
                tour.clear_result(db, t, rng.choice(played))
        if change_boards and rng.random() < 0.05:
            tour.set_boards(db, t, rng.randint(1, 4))
    _check(t)
    assert all(m.is_played for m in t.matches)


@pytest.mark.parametrize("seed", range(12))
def test_simulated_knockout(db, seed):
    rng = random.Random(seed)
    t = _new(db, rng.randint(3, 16), rng.randint(1, 4), tag=str(seed))
    _simulate(db, t, rng)
    assert tour.entry_by_id(t, t.winner_entry_id) is not None


@pytest.mark.parametrize("seed", range(12))
def test_simulated_groups(db, seed):
    rng = random.Random(100 + seed)
    groups = rng.randint(1, 3)
    n = rng.randint(2 * groups + 1, 4 * groups + 2)
    advance = rng.randint(1, max(1, n // groups - 1))
    if groups * advance < 2:
        advance = 2
    t = _new(db, n, rng.randint(1, 4), groups=groups, advance=advance, tag=f"g{seed}")
    _simulate(db, t, rng)


def test_matchday_order_and_queue(db):
    t = _new(db, 8, 4, groups=2)  # 2 Gruppen à 4: pro Spieltag 2 Spiele je Gruppe
    first = [m for m in t.matches if m.board]
    assert len(first) == 4 and {m.group_no for m in first} == {0, 1}
    # Spieltag 1: in jeder Gruppe spielen alle vier
    for g in (0, 1):
        assert len({e for m in first if m.group_no == g for e in (m.entry1_id, m.entry2_id)}) == 4
    view = tour.board_view(t)
    assert view["n"] == 4 and all(m for _, m in view["boards"]) and view["waiting"] == 8


def test_board_freed_and_reused(db):
    t = _new(db, 4, 1)  # 1 Scheibe, Halbfinale 1-4 und 2-3
    on = [m for m in t.matches if m.board == 1]
    assert len(on) == 1
    tour.set_result(db, t, on[0], 1, 0)
    nxt = [m for m in t.matches if m.board == 1 and not m.is_played]
    assert len(nxt) == 1 and nxt[0].round == 1  # zweites Halbfinale vor dem Finale
    tour.clear_result(db, t, on[0])  # erstes Halbfinale zurückgesetzt -> wartet, Scheibe ist belegt
    assert on[0].board is None and nxt[0].board == 1


def test_boards_off_and_on(db):
    t = _new(db, 6, 0)
    assert not any(m.board for m in t.matches)
    tour.set_boards(db, t, 2)
    assert len([m for m in t.matches if m.board]) == 2
    tour.set_boards(db, t, 1)
    assert len([m for m in t.matches if m.board and not m.is_played]) == 1
    tour.set_boards(db, t, 0)
    assert not any(m.board for m in t.matches if not m.is_played)
    with pytest.raises(tour.TournamentError):
        tour.set_boards(db, t, 99)


def test_boards_via_web(db, make_user):
    make_user("olli")
    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        r = c.post("/darts/tournaments/new", data={"name": "Board Cup", "start": 301, "legs": 1, "final_legs": 1,
                                                   "guests": "B1, B2, B3, B4, B5, B6", "boards": 2},
                   follow_redirects=False)
        assert r.status_code == 303, r.text[:400]
        t = db.scalar(select(models.Tournament))
        page = c.get(f"/darts/tournaments/{t.id}").text
        assert "Board 1" in page and "Board 2" in page and "Up next" not in page  # nur 2 spielbare Matches
        on = next(m for m in t.matches if m.board == 1)
        assert "Play on <strong>Board 1</strong>" in c.get(f"/darts/tournaments/{t.id}/matches/{on.id}").text
        r = c.post(f"/darts/tournaments/{t.id}/matches/{on.id}/play", follow_redirects=False)
        game_url = r.headers["location"]
        assert "Board 1" in c.get(game_url).text
        assert "LIVE" in c.get(f"/darts/tournaments/{t.id}").text
        # Organisator ändert die Anzahl
        c.post(f"/darts/tournaments/{t.id}/boards", data={"boards": "3"})
        db.expire_all()
        t = db.get(models.Tournament, t.id)
        # nur 2 spielbare Matches -> eine der 3 Scheiben bleibt frei
        assert tour.board_count(t) == 3 and len([m for m in t.matches if m.board and not m.is_played]) == 2
        assert "free – waiting for players" in c.get(f"/darts/tournaments/{t.id}").text
        assert "must be a whole number" in c.post(f"/darts/tournaments/{t.id}/boards", data={"boards": "x"}).text
        c.post(f"/darts/tournaments/{t.id}/boards", data={"boards": "1"})
        page = c.get(f"/darts/tournaments/{t.id}").text
        assert "Up next:" in page and "Board 2" not in page  # zweites Match wartet jetzt
    # Bierpong heißt es "Table"
    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        c.post("/beerpong/tournaments/new", data={"name": "Pong", "cups": 6, "mode": "fixed", "boards": 1,
                                                  "teams": "A: a1, a2\nB: b1, b2\nC: c1, c2"})
        t = db.scalars(select(models.Tournament).where(models.Tournament.sport == "beerpong")).first()
        assert "Table 1" in c.get(f"/beerpong/tournaments/{t.id}").text


def test_reset_upstream_frees_board(db):
    """Gefunden per Simulation: Reset vor einem schon zugeteilten Match darf keine Doppelbelegung erzeugen."""
    t = _new(db, 4, 2)
    s1, s2 = sorted((m for m in t.ko_matches if m.round == 1), key=lambda m: m.slot)
    final = next(m for m in t.ko_matches if m.round == 2)
    tour.set_result(db, t, s1, 1, 0)
    tour.set_result(db, t, s2, 1, 0)
    assert final.board is not None
    tour.clear_result(db, t, s2)  # Finale hat wieder nur einen Spieler
    assert final.board is None and s2.board is not None
    tour.set_result(db, t, s2, 0, 1)
    _check(t)
    assert final.board is not None


def test_groups_alternate_on_boards(db):
    t = _new(db, 8, 2, groups=2)
    on = sorted((m for m in t.matches if m.board), key=lambda m: m.board)
    assert [m.group_no for m in on] == [0, 1]  # eine Scheibe pro Gruppe
    q = tour.board_view(t)["queue"]
    assert [m.group_no for m in q[:2]] == [0, 1]  # Warteschlange wechselt ebenfalls ab
