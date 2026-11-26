"""Liga: jeder gegen jeden nach Spieltagen (optional Hin- und Rückrunde), Tabelle, Meister."""

from collections import Counter

import pytest
from fastapi.testclient import TestClient

from app import competitors, models
from app import tournaments as tour
from app.darts import service
from app.main import app


_n = iter(range(10**6))


def _league(db, n, rounds=1, sport="darts", **settings):
    ids = [[competitors.create_guest(db, f"P{next(_n)}").id] for _ in range(n)]
    return tour.create_tournament(db, sport, "League", ids, {"start": 301, "legs": 2, "final_legs": 3, **settings},
                                  None, league_rounds=rounds)


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6, 7, 8])
@pytest.mark.parametrize("rounds", [1, 2])
def test_schedule(db, n, rounds):
    t = _league(db, n, rounds)
    ms = t.group_matches
    assert t.is_league and t.has_groups and not t.ko_matches
    assert len(ms) == rounds * n * (n - 1) // 2
    pairs = Counter(frozenset((m.entry1_id, m.entry2_id)) for m in ms)
    assert set(pairs.values()) == {rounds}  # jeder gegen jeden, ein- bzw. zweimal
    days = n - 1 if n % 2 == 0 else n
    assert t.matchdays == rounds * days
    for d in range(1, t.matchdays + 1):  # niemand spielt zweimal am selben Spieltag
        playing = [e for m in ms if m.matchday == d for e in (m.entry1_id, m.entry2_id)]
        assert len(playing) == len(set(playing)) and playing
    if rounds == 2:  # Rückrunde: Seiten getauscht
        home = Counter((m.entry1_id, m.entry2_id) for m in ms)
        assert set(home.values()) == {1}
        first = {(m.entry1_id, m.entry2_id) for m in ms if m.matchday <= days}
        second = {(m.entry2_id, m.entry1_id) for m in ms if m.matchday > days}
        assert first == second
    # Heimrecht (wirft zuerst) einigermaßen verteilt
    starts = Counter(m.entry1_id for m in ms)
    assert max(starts.values()) - min(starts.values(), default=0) <= max(2, rounds)


def test_table_and_champion(db):
    t = _league(db, 3)
    e = {x.seed: x.id for x in t.entries}
    results = {frozenset((e[1], e[2])): e[1], frozenset((e[1], e[3])): e[1], frozenset((e[2], e[3])): e[3]}
    for i, m in enumerate(sorted(t.group_matches, key=lambda m: m.matchday)):
        win = results[frozenset((m.entry1_id, m.entry2_id))]
        s1, s2 = (2, 1) if win == m.entry1_id else (0, 2)
        service.record_tournament_result(db, t, m, s1, s2)
        if i < 2:
            assert t.status == "running" and t.winner_entry_id is None
    assert t.status == "finished" and t.winner_entry_id == e[1]
    view = tour.league_view(t)
    assert [s.entry.id for s in view["rows"]] == [e[1], e[3], e[2]]
    assert view["current"] is None and all(d["done"] for d in view["days"])
    places = [r.place for r in tour.entry_results(t)]
    assert places == ["Champion", "2nd", "3rd"]
    assert not tour.knockout_started(t)
    # Ergebnis nachträglich ändern -> neuer Meister; Ergebnis löschen -> Liga läuft wieder
    m = next(m for m in t.group_matches if {m.entry1_id, m.entry2_id} == {e[1], e[3]})
    assert tour.can_change(t, m)
    a, b = (0, 2) if m.entry1_id == e[1] else (2, 0)
    service.record_tournament_result(db, t, m, a, b)  # jetzt gewinnt 3 -> 3 hat 2 Siege, 1 hat 1
    assert t.winner_entry_id == e[3]
    tour.clear_result(db, t, m)
    assert t.status == "running" and t.winner_entry_id is None and tour.league_view(t)["current"] is not None


def test_league_titles_and_validation(db):
    t = _league(db, 4, 2)
    m = sorted(t.group_matches, key=lambda m: m.slot)[0]
    assert tour.match_title(t, m) == "Matchday 1"
    assert not tour.is_final(t, m) and service.legs_for(t, m) == 2
    assert tour.format_label(t) == "league · home & away"
    with pytest.raises(tour.TournamentError):
        _league(db, 3, rounds=3)
    with pytest.raises(tour.TournamentError):
        _league(db, tour.MAX_LEAGUE + 1)


def test_league_boards_follow_matchdays(db):
    t = _league(db, 6, boards=3)
    on = [m for m in t.group_matches if m.board]
    assert len(on) == 3 and {m.matchday for m in on} == {1}
    for m in on:
        service.record_tournament_result(db, t, m, 2, 0)
    nxt = [m for m in t.group_matches if m.board and not m.is_played]
    # Spieltag 2 kommt zuerst dran; ist ein Spieler noch beschäftigt, rückt ein Spiel von Spieltag 3 vor,
    # damit keine Scheibe leer steht
    assert len(nxt) >= 2 and min(m.matchday for m in nxt) == 2 and max(m.matchday for m in nxt) <= 3
    busy = [e for m in nxt for e in (m.entry1_id, m.entry2_id)]
    assert len(busy) == len(set(busy))  # niemand auf zwei Scheiben


@pytest.fixture
def olli(db, make_user):
    make_user("olli")
    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        yield c


def test_league_pages(olli, db):
    r = olli.post("/darts/tournaments/new", data={"name": "Winter League", "start": 501, "legs": 2, "final_legs": 3,
                                                   "guests": "Anna, Ben, Carl, Dora", "format": "league",
                                                   "league_rounds": "2"}, follow_redirects=False)
    assert r.status_code == 303, r.text[:400]
    tid = int(r.headers["location"].rsplit("/", 1)[1])
    t = db.get(models.Tournament, tid)
    assert t.is_league and t.settings["rounds"] == 2 and len(t.group_matches) == 12
    page = olli.get(f"/darts/tournaments/{tid}").text
    assert "League table" in page and "Matchday 6" in page and "home &amp; away" in page
    assert "knockout bracket appears" not in page and "Group stage" not in page
    lst = olli.get("/darts/leagues").text
    assert "league · home &amp; away" in lst and "Winter League" in lst and "Matchday 1 of 6" in lst
    assert "Winter League" not in olli.get("/darts/tournaments").text  # Ligen stehen nicht bei den Turnieren
    assert '<a href="/darts/leagues" aria-current="page">' in page  # Liga-Seite: Reiter "Leagues" aktiv
    m = t.group_matches[0]
    assert "Matchday 1" in olli.get(f"/darts/tournaments/{tid}/matches/{m.id}").text
    assert olli.get(f"/darts/tournaments/{tid}/tv").status_code == 200
    assert "Table" in olli.get(f"/darts/tournaments/{tid}/tv?partial=1").text
    # Beer Pong kann es auch
    r = olli.post("/beerpong/tournaments/new", data={"name": "Pong League", "mode": "fixed", "teams": "A & B\nC & D\nE & F",
                                                      "format": "league", "league_rounds": "1", "cups": 6},
                  follow_redirects=False)
    assert r.status_code == 303, r.text[:400]
    bp = db.get(models.Tournament, int(r.headers["location"].rsplit("/", 1)[1]))
    assert bp.is_league and len(bp.group_matches) == 3
    assert "League table" in olli.get(f"/beerpong/tournaments/{bp.id}").text
    # Eigenes Formular für Ligen, das Turnier-Formular bietet keine Liga mehr an
    lf = olli.get("/darts/leagues/new").text
    assert "New league" in lf and 'name="format" value="league"' in lf and "Create league" in lf
    assert "Final: first to" not in lf
    tf = olli.get("/darts/tournaments/new").text
    assert 'value="league"' not in tf and "Groups + KO" in tf
    assert "New league" in olli.get("/beerpong/leagues/new").text
    assert "Pong League" in olli.get("/beerpong/leagues").text and "Pong League" not in olli.get("/beerpong/tournaments").text
    # Hall of Fame getrennt: Ligatitel zählen nur bei den Ligen
    for m in bp.group_matches:
        tour.set_result(db, bp, m, 6, 2)
    assert "League champions" in olli.get("/beerpong/leagues").text
    assert "Hall of fame" not in olli.get("/beerpong/tournaments").text
