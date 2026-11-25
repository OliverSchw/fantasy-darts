"""Elo, Formkurve, Erfolge, Neuigkeiten, Diagramm-Geometrie."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import charts, competitors, feed, models
from app import tournaments as tour
from app.darts import service
from app.darts.achievements import ACHIEVEMENTS, compute_achievements
from app.darts.rating import START, compute_elo, expected, form_curve
from app.main import app


def _guests(db, *names):
    return [competitors.create_guest(db, n).id for n in names]


def _play(db, ids, visits, start=301, team_size=1):
    """visits = [(score, darts)] in Wurfreihenfolge; darts None = 3."""
    g = service.create_game(db, start, 1, ids, None, team_size=team_size)
    for i, (score, darts) in enumerate(visits):
        service.add_visit(db, g, score, darts, i)
    return g


def win_301(db, a, b):
    """a gewinnt 301 gegen b: 180, 0, 121 Checkout."""
    return _play(db, [a, b], [(180, None), (0, None), (121, 3)])


def test_expected_and_elo_basics(db):
    assert expected(1000, 1000) == pytest.approx(0.5)
    assert expected(1400, 1000) == pytest.approx(10 / 11)
    a, b, c = _guests(db, "Anna", "Ben", "Carl")
    win_301(db, a, b)
    elo = compute_elo(db)
    assert elo.rating(a) == pytest.approx(1016) and elo.rating(b) == pytest.approx(984)
    assert elo.rating(c) == START and c not in elo.ratings
    assert elo.provisional(a) and elo.rank(a) is None
    win_301(db, a, b)
    elo = compute_elo(db)
    gain2 = elo.history[a][-1].delta
    assert 0 < gain2 < 16  # Favorit gewinnt weniger
    assert sum(elo.ratings.values()) == pytest.approx(2 * START)  # Nullsumme
    # Abgebrochene und laufende Spiele zählen nicht, Solo-Spiele auch nicht
    g = service.create_game(db, 301, 1, [a, b], None)
    service.abandon(db, g)
    service.create_game(db, 301, 1, [a, c], None)
    _play(db, [c], [(180, None), (121, 3)])
    assert compute_elo(db).games == {a: 2, b: 2}


def test_elo_rank_and_doubles(db):
    a, b, c, d = _guests(db, "A", "B", "C", "D")
    for _ in range(5):
        win_301(db, a, b)
    elo = compute_elo(db)
    assert elo.rank(a) == 1 and elo.rank(b) == 2
    # Doppel: A & C gegen B & D (Reihenfolge A, B, C, D), Team 1 gewinnt
    g = _play(db, [a, b, c, d], [(180, None), (0, None), (121, 3)], team_size=2)
    elo2 = compute_elo(db)
    da, dc = elo2.deltas[g.id][a], elo2.deltas[g.id][c]
    assert da == dc > 0 and elo2.deltas[g.id][b] == elo2.deltas[g.id][d] == -da


def test_elo_multiplayer_and_party_modes(db):
    a, b, c = _guests(db, "A", "B", "C")
    g = _play(db, [a, b, c], [(180, None), (0, None), (0, None), (121, 3)])
    elo = compute_elo(db)
    assert elo.deltas[g.id][a] == pytest.approx(16)  # 2 Gegner, K wird geteilt
    assert elo.deltas[g.id][b] == elo.deltas[g.id][c] == pytest.approx(-8)
    # Partyspiel zählt mit
    m = service.create_mode_game(db, "atc", [b, c], None)
    m.status, m.winner_side, m.winner_id = "finished", 0, b
    db.commit()
    assert compute_elo(db).games[b] == 2


def test_form_curve(db):
    a, b = _guests(db, "A", "B")
    win_301(db, a, b)  # a: 301 in 6 Darts -> 150.5
    _play(db, [a, b], [(26, None), (180, None), (0, None), (121, 3)])  # b gewinnt, a: 26 + 0 in 6 Darts
    pts = form_curve(db, a)
    assert [round(p.average, 1) for p in pts] == [150.5, 13.0]
    assert [p.won for p in pts] == [True, False]
    assert len(form_curve(db, a, limit=1)) == 1 and form_curve(db, a, limit=1)[0].average == 13


def test_achievements(db):
    a, b = _guests(db, "A", "B")
    # 501: a 180, b 0, a 180, b 0, a 141 Checkout (3 Darts) -> 9-Darter!
    _play(db, [a, b], [(180, None), (0, None), (180, None), (0, None), (141, 3)], start=501)
    got = {e.key for e in compute_achievements(db)[a]}
    assert {"first_win", "ton", "ton80", "ton_out", "short_leg", "twelve", "avg60", "avg80"} <= got
    assert "big_fish" not in got and "club180" not in got
    assert "first_win" not in {e.key for e in compute_achievements(db).get(b, [])}
    # 170er Checkout und Bull-Finish
    _play(db, [b, a], [(131, None), (0, None), (170, 3)])
    _play(db, [b, a], [(180, None), (0, None), (71, None), (0, None), (50, 1)])
    got_b = {e.key for e in compute_achievements(db)[b]}
    assert {"big_fish", "bull_finish", "ton_out", "first_win"} <= got_b
    # Turniersieg
    t = tour.create_tournament(db, "darts", "Cup", [[a], [b]], {"start": 301, "legs": 1, "final_legs": 1}, None)
    service.record_tournament_result(db, t, t.matches[0], 1, 0)
    champ = t.matches[0].entry1.competitors[0].id
    assert "champion" in {e.key for e in compute_achievements(db)[champ]}
    assert all(k in ACHIEVEMENTS for e in compute_achievements(db).values() for k in [x.key for x in e])


def test_shanghai_and_party_animal(db):
    a, b = _guests(db, "A", "B")
    g = service.create_mode_game(db, "shanghai", [a, b], None, {"rounds": 7})
    service.add_mode_visit(db, g, ["S1", "D1", "T1"], 0)
    assert g.status == "finished"
    assert "shanghai" in {e.key for e in compute_achievements(db)[a]}
    for mode in ("cricket", "atc", "killer"):
        m = service.create_mode_game(db, mode, [a, b], None)
        m.status, m.winner_side, m.winner_id = "finished", 0, a
        db.commit()
    assert "party" in {e.key for e in compute_achievements(db)[a]}


def test_news_feed(db):
    a, b = _guests(db, "Anna", "Ben")
    _play(db, [a, b], [(180, None), (0, None), (180, None), (0, None), (141, 3)], start=501)
    items = feed.news(db)
    texts = [i.text for i in items]
    assert any(t.startswith("Anna beat Ben 1:0 (501) · +16 Elo") for t in texts)
    assert texts.count("Anna threw a 180") == 2 and "Anna checked out 141" in texts
    assert any("unlocked “Twelve-darter”" in t for t in texts)
    assert not any("unlocked “Maximum”" in t for t in texts)  # steht schon als 180 da
    assert all(i.at >= items[-1].at for i in items)  # neueste zuerst
    assert not any(i.result for i in feed.news(db, "darts", results=False))
    # Beer Pong + Turnier
    t = tour.create_tournament(db, "beerpong", "Pong Night", [[a], [b]], {}, None)
    tour.set_result(db, t, t.matches[0], 6, 3)
    bp = feed.news(db, "beerpong")
    assert bp and bp[0].text.endswith("won Pong Night") and bp[0].url == f"/beerpong/tournaments/{t.id}"
    assert all(i.sport == "beerpong" for i in bp)
    assert len(feed.news(db, limit=3)) == 3


def test_line_chart():
    assert charts.line_chart([]) is None and charts.line_chart([(1, "a", False)]) is None
    ch = charts.line_chart([(40, "01.01. · 40", False), (60, "02.01. · 60", True), (50, "03.01. · 50", False)],
                           baseline=45)
    ys = [p.y for p in ch["points"]]
    assert ys[1] < ys[2] < ys[0]  # höher = weiter oben
    assert ch["points"][0].x == charts.LEFT and ch["points"][-1].x == charts.W - charts.RIGHT
    assert ch["ticks"][0]["y"] >= ch["points"][0].y and ch["first"] == "01.01." and ch["last"] == "03.01."
    assert ch["points"][1].hollow and ch["baseline"] is not None
    flat = charts.line_chart([(1000, "x", False), (1000, "y", False)])
    assert flat and len({p.y for p in flat["points"]}) == 1


@pytest.fixture
def olli(db, make_user):
    make_user("olli")
    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        yield c


def test_pages(olli, db):
    me = competitors.competitor_for_user(db, db.scalar(select(models.User))).id
    (b,) = _guests(db, "Ben")
    for _ in range(3):
        win_301(db, me, b)
    r = olli.get(f"/darts/players/{me}")
    assert r.status_code == 200
    assert "Elo rating" in r.text and "Provisional (3/5 games)" in r.text
    assert 'class="chart"' in r.text and "Achievements" in r.text and "First win" in r.text
    assert olli.get(f"/darts/players/{b}").status_code == 200
    assert "Elo" in olli.get("/darts/players").text
    home = olli.get("/darts").text
    assert "Elo rating" in home and "📰 News" in home
    hub = olli.get("/").text
    assert "📰 News" in hub and "olli beat Ben" in hub
    with TestClient(app) as anon:  # ohne Login keine Neuigkeiten auf der Startseite
        assert "📰 News" not in anon.get("/").text


def test_cache_follows_changes(db):
    a, b = _guests(db, "A", "B")
    win_301(db, a, b)
    first = compute_elo(db)
    assert compute_elo(db) is first  # nichts geändert -> aus dem Zwischenspeicher
    g = win_301(db, b, a)
    assert compute_elo(db).games[a] == 2
    service.undo_last(db, g)  # Spiel läuft wieder -> zählt nicht mehr
    assert compute_elo(db).games[a] == 1
    service.abandon(db, g)
    assert compute_elo(db).games[a] == 1
    got = compute_achievements(db)
    assert compute_achievements(db) is got
    c = service.create_game(db, 301, 1, [a, b], None)
    service.add_visit(db, c, 180, None, 0)
    assert compute_achievements(db) is not got
