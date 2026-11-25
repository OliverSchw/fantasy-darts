"""K.-o.-Turniere: Setzliste, Freilose, Weiterrücken, Darts-Anbindung."""

import pytest
from conftest import double_answer
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import competitors, models
from app import tournaments as tour
from app.darts import service
from app.main import app


def _guests(db, n):
    return [competitors.create_guest(db, f"Player {i}").id for i in range(1, n + 1)]


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
        dbl = double_answer(game, data["score"], data.get("darts"))
        if dbl is not None:
            data["double_darts"] = dbl
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
    assert "Champion: <strong>" in olli.get(f"/darts/tournaments/{t.id}").text

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


# ---------------------------------------------------------------- Gruppenphase


def _gt(db, n, groups, advance=2, sport="darts"):
    return tour.create_tournament(db, sport, "Cup", [[c] for c in _guests(db, n)], {"start": 301, "legs": 1}, None,
                                  groups=groups, advance=advance)


def _play_groups(db, t, winner_by=lambda m: 1):
    """Alle Gruppenspiele eintragen; winner_by(m) -> 1 oder 2."""
    for m in list(t.group_matches):
        if not m.is_played:
            tour.set_result(db, t, m, *((2, 0) if winner_by(m) == 1 else (0, 2)))


def test_groups_snake_and_round_robin(db):
    t = _gt(db, 8, groups=2)
    groups = {g: sorted(e.seed for e in t.entries if e.group_no == g) for g in (0, 1)}
    assert groups == {0: [1, 4, 5, 8], 1: [2, 3, 6, 7]}  # Schlangenlinie
    assert len(t.group_matches) == 12 and t.num_rounds == 0 and not tour.knockout_started(t)
    pairs = {frozenset((m.entry1_id, m.entry2_id)) for m in t.group_matches}
    assert len(pairs) == 12  # jeder gegen jeden, keine Doppel
    # Spieltage: in den ersten 2 Spielen einer Gruppe spielt jeder genau einmal
    g0 = [m for m in t.group_matches if m.group_no == 0]
    assert len({g0[0].entry1_id, g0[0].entry2_id, g0[1].entry1_id, g0[1].entry2_id}) == 4


def test_group_validation(db):
    ids = _guests(db, 5)
    with pytest.raises(tour.TournamentError, match="at least 6"):
        tour.create_tournament(db, "darts", "Cup", [[i] for i in ids], {}, None, groups=3)
    with pytest.raises(tour.TournamentError, match="at most 1"):
        tour.create_tournament(db, "darts", "Cup", [[i] for i in ids[:4]], {}, None, groups=2, advance=2)


def test_standings_and_crossover_knockout(db):
    t = _gt(db, 8, groups=2)
    seed = lambda eid: tour.entry_by_id(t, eid).seed  # noqa: E731
    # Der besser Gesetzte gewinnt immer
    _play_groups(db, t, winner_by=lambda m: 1 if seed(m.entry1_id) < seed(m.entry2_id) else 2)
    table = tour.standings(t)
    assert [s.entry.seed for s in table[0]] == [1, 4, 5, 8] and table[0][0].won == 3 and table[0][0].diff == 6
    assert tour.knockout_started(t) and t.num_rounds == 2
    semis = sorted((m for m in t.ko_matches if m.round == 1), key=lambda m: m.slot)
    assert [(seed(m.entry1_id), seed(m.entry2_id)) for m in semis] == [(1, 3), (2, 4)]  # A1-B2, B1-A2
    # Gruppenergebnisse sind jetzt gesperrt
    with pytest.raises(tour.TournamentError, match="knockout stage has already started"):
        tour.set_result(db, t, t.group_matches[0], 0, 2)
    # K.-o. zurücksetzen -> Gruppen wieder änderbar, Baum entsteht neu
    tour.reset_knockout(db, t)
    assert not tour.knockout_started(t) and t.num_rounds == 0
    tour.clear_result(db, t, t.group_matches[0])
    assert not tour.knockout_started(t)
    m = t.group_matches[0]
    tour.set_result(db, t, m, 2, 1)
    assert tour.knockout_started(t)
    # Mit gespieltem K.-o.-Match lässt sich der K.-o. nicht mehr zurücksetzen
    semi = next(m for m in t.ko_matches if m.round == 1)
    tour.set_result(db, t, semi, 1, 0)
    with pytest.raises(tour.TournamentError, match="already have results"):
        tour.reset_knockout(db, t)


def test_three_groups_fall_back_to_seeded_bracket(db):
    t = _gt(db, 9, groups=3)  # 3 Gruppen à 3, je 2 weiter -> 6 im K.-o., 2 Freilose
    _play_groups(db, t)
    assert tour.knockout_started(t) and t.num_rounds == 3
    assert len([m for m in t.ko_matches if m.bye]) == 2
    assert all(tour.entry_by_id(t, m.winner_id) for m in t.ko_matches if m.bye)


def test_head_to_head_breaks_ties(db):
    t = _gt(db, 4, groups=1, advance=2)
    e = {x.seed: x.id for x in t.entries}
    by_pair = {frozenset((m.entry1_id, m.entry2_id)): m for m in t.group_matches}

    def res(a, b, sa, sb):
        m = by_pair[frozenset((e[a], e[b]))]
        tour.set_result(db, t, m, *((sa, sb) if m.entry1_id == e[a] else (sb, sa)))
    # 1 und 2 haben gleiche Bilanz (2 Siege, +2, 4 Legs); 2 hat 1 direkt geschlagen
    res(2, 1, 1, 0); res(1, 3, 2, 1); res(1, 4, 2, 1)
    res(2, 3, 2, 1); res(4, 2, 2, 1)
    res(3, 4, 1, 0)
    rows = tour.standings(t)[0]
    top = [s.entry.seed for s in rows[:2]]
    assert {top[0], top[1]} == {1, 2}
    a, b = rows[0], rows[1]
    if (a.won, a.diff, a.score_for) == (b.won, b.diff, b.score_for):
        assert a.entry.seed == 2  # direkter Vergleich


def test_group_tournament_via_web(olli, db):
    r = olli.post("/darts/tournaments/new", data={"name": "Group Cup", "start": 301, "legs": 1, "final_legs": 1,
                                                  "guests": "A1, A2, A3, A4, A5, A6", "format": "groups",
                                                  "groups": 2, "advance": 2}, follow_redirects=False)
    assert r.status_code == 303, r.text[:400]
    t = db.scalar(select(models.Tournament))
    page = olli.get(f"/darts/tournaments/{t.id}").text
    assert "Group A" in page and "Group B" in page and "appears here once all group matches" in page
    gm = t.group_matches[0]
    # Gruppenspiel live spielen: Darts-Spiel mit 1 Leg (nicht die Final-Legs)
    r = olli.post(f"/darts/tournaments/{t.id}/matches/{gm.id}/play", follow_redirects=False)
    game = db.get(models.DartsGame, int(r.headers["location"].rsplit("/", 1)[1]))
    assert game.legs_to_win == 1 and "Group A" in olli.get(f"/darts/games/{game.id}").text
    _play_out(olli, db, game)
    db.expire_all()
    assert db.get(models.TournamentMatch, gm.id).is_played
    # Rest per Hand -> K.-o. entsteht automatisch
    t = db.get(models.Tournament, t.id)
    last = None
    for m in t.group_matches:
        if not m.is_played:
            last = olli.post(f"/darts/tournaments/{t.id}/matches/{m.id}/result", data={"score1": 1, "score2": 0})
    assert "knockout stage is drawn" in last.text
    page = olli.get(f"/darts/tournaments/{t.id}").text
    assert "Knockout" in page and "Semi-finals" in page
    # Gesperrtes Gruppenspiel zeigt den Grund
    assert "reset it first" in olli.get(f"/darts/tournaments/{t.id}/matches/{gm.id}").text
    olli.post(f"/darts/tournaments/{t.id}/knockout/reset")
    db.expire_all()
    assert not tour.knockout_started(db.get(models.Tournament, t.id))
    # Ungültiges Format wird abgelehnt
    r = olli.post("/darts/tournaments/new", data={"name": "X", "start": 301, "legs": 1, "final_legs": 1,
                                                  "guests": "B1, B2, B3", "format": "groups", "groups": 2})
    assert r.status_code == 400 and "at least 4" in r.text


def test_manual_darts_result_must_match_legs(olli, db):
    olli.post("/darts/tournaments/new", data={"name": "Legs", "start": 501, "legs": 2, "final_legs": 3,
                                              "guests": "L1, L2, L3, L4"})
    t = db.scalar(select(models.Tournament))
    semi = next(m for m in t.ko_matches if m.round == 1)
    for bad in ((5, 0), (2, 2), (1, 0), (3, 1)):
        r = olli.post(f"/darts/tournaments/{t.id}/matches/{semi.id}/result", data={"score1": bad[0], "score2": bad[1]})
        assert "first to 2 legs" in r.text, bad
    olli.post(f"/darts/tournaments/{t.id}/matches/{semi.id}/result", data={"score1": 2, "score2": 1})
    db.expire_all()
    assert db.get(models.TournamentMatch, semi.id).is_played
    final = next(m for m in db.get(models.Tournament, t.id).ko_matches if m.round == 2)
    r = olli.post(f"/darts/tournaments/{t.id}/matches/{final.id}/result", data={"score1": 2, "score2": 0})
    assert "Both sides" in r.text or "first to 3" in r.text  # Finale: first to 3


# ---------------------------------------------------------------- Turnier-Stats, Hall of Fame, Rechte


def test_entry_results_places(db):
    t = _t(db, 4)  # Halbfinale 1-4, 2-3
    seed = lambda eid: tour.entry_by_id(t, eid).seed  # noqa: E731
    s1, s2 = sorted((m for m in t.ko_matches if m.round == 1), key=lambda m: m.slot)
    tour.set_result(db, t, s1, 1, 0)  # 1 schlägt 4
    tour.set_result(db, t, s2, 0, 1)  # 3 schlägt 2
    final = next(m for m in t.ko_matches if m.round == 2)
    tour.set_result(db, t, final, 0, 1)  # 3 wird Champion
    places = {r.entry.seed: (r.place, r.won, r.lost) for r in tour.entry_results(t)}
    assert places[3] == ("Champion", 2, 0) and places[1] == ("Runner-up", 1, 1)
    assert places[2][0] == places[4][0] == "Semi-finals"
    assert [r.entry.seed for r in tour.entry_results(t)][:2] == [3, 1]


def test_group_exit_place(db):
    t = _gt(db, 6, groups=2, advance=1)
    _play_groups(db, t)
    res = tour.entry_results(t)
    assert sum(r.out_in_groups for r in res) == 4 and all(r.place == "Group stage" for r in res if r.out_in_groups)


def test_tournament_stats_and_hall_of_fame(olli, db):
    olli.post("/darts/tournaments/new", data={"name": "Mini", "start": 301, "legs": 1, "final_legs": 1,
                                              "guests": "P1, P2"})
    t = db.scalar(select(models.Tournament))
    final = t.ko_matches[0]
    r = olli.post(f"/darts/tournaments/{t.id}/matches/{final.id}/play", follow_redirects=False)
    game = db.get(models.DartsGame, int(r.headers["location"].rsplit("/", 1)[1]))
    _play_out(olli, db, game)  # Spieler auf Position 0 gewinnt mit 180 / 81 / 40
    page = olli.get(f"/darts/tournaments/{t.id}").text
    assert "Standings &amp; stats" in page and "🏆 Champion" in page and "Runner-up" in page
    assert "180.0" not in page and ">1</td>" in page  # 180er-Spalte gefüllt
    lst = olli.get("/darts/tournaments").text
    assert "Hall of fame" in lst and "1 title" in lst
    db.rollback()  # offene Lese-Transaktion des Tests beenden -> aktuellen Stand sehen
    db.expire_all()
    champ = tour.entry_by_id(db.get(models.Tournament, t.id), db.get(models.Tournament, t.id).winner_entry_id)
    assert tour.hall_of_fame(db, "darts")[0] == (champ.competitors[0], 1)


def test_organizer_can_score_games_started_by_players(db, make_user):
    boss, anna, kai = make_user("orga"), make_user("anna"), make_user("kai")
    a = competitors.competitor_for_user(db, anna)
    b = competitors.competitor_for_user(db, kai)
    t = tour.create_tournament(db, "darts", "Cup", [[a.id], [b.id]], {"start": 301, "legs": 1}, boss)
    final = t.ko_matches[0]
    game = service.start_tournament_game(db, t, final, anna)  # anna startet ihr Match selbst
    assert service.can_score(boss, game)  # Organisator (kein Admin, spielt nicht mit) darf zählen
    stranger = make_user("zuschauer")
    assert not service.can_score(stranger, game)
