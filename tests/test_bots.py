"""Darts-Bots: Zielwahl, Stärke, automatisches Werfen, Undo, Training (nicht in Elo/Siegen/Neuigkeiten)."""

import random

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import competitors, feed, models
from app.darts import service
from app.darts.achievements import compute_achievements
from app.darts.bot import LEVELS, bot_visit, choose_aim, throw_dart
from app.darts.engine import DartsError, advance, new_state
from app.darts.rating import compute_elo
from app.darts.stats import bot_records, compute_stats
from app.darts.throws import x01_visit
from app.main import app


def test_choose_aim():
    assert choose_aim(501, 3) == "T20"
    assert choose_aim(121, 3) == "T20"  # Checkout-Weg T20 T15 D8
    assert choose_aim(40, 1) == "D20" and choose_aim(32, 1) == "D16" and choose_aim(50, 1) == "DB"
    assert choose_aim(41, 1) == "S9"  # 32 übrig lassen
    assert choose_aim(3, 1) == "S1"  # D1 übrig, kein Bust
    for rest in range(2, 171):  # Zielen führt nie absichtlich in den Bust
        for left in (1, 2, 3):
            from app.darts.modes import parse_dart
            m, n = parse_dart(choose_aim(rest, left))
            assert rest - m * n >= 2 or (rest - m * n == 0 and m == 2), (rest, left)


def test_throw_dart_codes_valid():
    rng = random.Random(3)
    from app.darts.modes import parse_dart
    for level in LEVELS.values():
        for aim in ("T20", "D16", "S5", "DB", "SB", "T1", "D1"):
            for _ in range(200):
                parse_dart(throw_dart(aim, level, rng))  # wirft bei ungültigen Codes


def _leg_average(level, legs=300, seed=1):
    rng = random.Random(seed)
    darts = pts = 0
    for _ in range(legs):
        st = new_state(501, 1, 1)
        while not st.finished:
            v = x01_visit(st, bot_visit(st, level, rng))
            darts += v.darts
            pts += v.score
            advance(st, v)
    return 3 * pts / darts


def test_levels_are_ordered_and_close_to_target():
    avgs = {k: _leg_average(lv) for k, lv in LEVELS.items()}
    assert avgs["easy"] < avgs["medium"] < avgs["hard"] < avgs["pro"]
    for k, lv in LEVELS.items():
        assert abs(avgs[k] - lv.average) < 8, (k, avgs[k])


def test_bot_visit_ends_on_checkout_or_bust():
    rng = random.Random(5)
    for _ in range(300):
        st = new_state(301, 1, 1)
        while not st.finished:
            th = bot_visit(st, LEVELS["hard"], rng)
            v = x01_visit(st, th)  # muss gültig sein (keine Darts nach Ende)
            if v.checkout:
                assert th[-1].startswith("D")
            advance(st, v)


@pytest.fixture
def seeded():
    old = service.bot_rng
    service.bot_rng = random.Random(42)
    yield
    service.bot_rng = old


def test_game_vs_bot_flow(db, seeded):
    me = competitors.create_guest(db, "Me").id
    bot = competitors.bot(db, "pro")
    assert competitors.bot(db, "pro").id == bot.id  # nur einmal angelegt
    assert bot.is_bot and not bot.is_guest and bot not in competitors.all_competitors(db)
    g = service.create_game(db, 301, 1, [me, bot.id], None)
    assert len(g.visits) == 0
    service.add_visit(db, g, 60, None, 0)
    assert len(g.visits) == 2 and g.visits[1].competitor_id == bot.id and g.visits[1].throws  # Bot hat geworfen
    with pytest.raises(DartsError):
        service.add_visit(db, g, 60, None, 1)  # veraltet (Bot hat schon geworfen)
    # Undo nimmt die Bot-Aufnahme und die eigene zurück
    assert service.undo_last(db, g) and len(g.visits) == 0
    # Spiel zu Ende spielen: der Mensch wirft nur 0 -> der Bot gewinnt
    seq = 0
    while g.status == "live":
        service.add_visit(db, g, 0, None, seq)
        seq = len(g.visits)
    assert g.winner_id == bot.id
    # Bot wirft zuerst
    g2 = service.create_game(db, 301, 1, [bot.id, me], None)
    assert len(g2.visits) == 1 and g2.visits[0].competitor_id == bot.id
    assert not service.undo_last(db, g2)  # nur Bot-Aufnahmen -> nichts zurückzunehmen
    with pytest.raises(DartsError):
        service.create_game(db, 301, 1, [bot.id, competitors.bot(db, "easy").id], None)  # nur Bots


def test_bot_games_are_training(db, seeded):
    a, b = (competitors.create_guest(db, n).id for n in ("A", "B"))
    easy = competitors.bot(db, "easy").id
    g = service.create_game(db, 301, 1, [a, easy], None)
    service.add_visit(db, g, 180, None, 0)
    service.add_visit(db, g, 121, 3, len(g.visits))  # A checkt aus (falls der Bot nicht schon fertig ist)
    assert g.status == "finished" and g.winner_id == a
    st = compute_stats(db)[a]
    assert st.max180 == 1 and st.games == 0 and st.wins == 0  # Würfe zählen, Sieg nicht
    assert a not in compute_elo(db).ratings
    assert "first_win" not in {e.key for e in compute_achievements(db).get(a, [])}
    assert easy not in compute_achievements(db)
    assert [(b.bot_level, w, n) for b, w, n in bot_records(db, a)] == [("easy", 1, 1)]
    assert not any(i.result for i in feed.news(db)) and not any("Bot" in i.text for i in feed.news(db))
    # Doppel mit Bot als Partner: Bilanz zählt nur gegen gegnerische Bots
    g2 = service.create_game(db, 301, 1, [a, b, easy, competitors.bot(db, "hard").id], None, team_size=2)
    assert g2.has_bot
    with pytest.raises(competitors.CompetitorError):
        competitors.create_guest(db, "pro bot")  # Name ist reserviert


@pytest.fixture
def olli(db, make_user):
    make_user("olli")
    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        yield c


def test_web(olli, db, seeded):
    me = competitors.competitor_for_user(db, db.scalar(select(models.User))).id
    form = olli.get("/darts/new?bot=hard").text
    assert 'value="bot:hard"' in form and "Hard Bot · avg ~75" in form and '"bot:hard"' in form
    r = olli.post("/darts/new", data={"mode": "x01", "start": 501, "legs": 1, "p0": str(me), "p1": "bot:hard"},
                  follow_redirects=False)
    gid = int(r.headers["location"].rsplit("/", 1)[1])
    r = olli.post(f"/darts/games/{gid}/visit", data={"seq": 0, "score": 100})
    assert "🤖 Hard Bot:" in r.text and "🤖 Hard Bot</a>" in r.text
    assert olli.post("/darts/new", data={"mode": "cricket", "p0": str(me), "p1": "bot:easy"}).status_code == 400
    bot_id = db.scalar(select(models.Competitor.id).where(models.Competitor.bot_level == "hard"))
    page = olli.get(f"/darts/players/{bot_id}").text
    assert "Play this bot" in page
    assert "Hard Bot" not in olli.get("/darts/players").text  # nicht in der Rangliste
    assert "vs Bot" in olli.get("/darts").text


# ---------------------------------------------------------------- Eigene Bots


def test_calibration_hits_target():
    from app.darts.bot import calibrate, simulate_average, skill_level
    for avg, dbl in ((40, 15), (65, 30), (90, 45)):
        lv = skill_level(calibrate(avg, dbl), dbl)
        assert abs(simulate_average(lv, legs=400, seed=123) - avg) < 5, (avg, dbl)
    assert calibrate(40, 15) < calibrate(65, 30) < calibrate(90, 45)


def test_custom_bot_and_player_bot(db, seeded):
    from app.darts.stats import player_profile
    with pytest.raises(competitors.CompetitorError):
        competitors.custom_bot(db, 150, 30)
    with pytest.raises(competitors.CompetitorError):
        competitors.custom_bot(db, 60, 90)
    b = competitors.custom_bot(db, 62.4, 29.6)
    assert b.name == "Bot 62 avg · 30%" and b.bot_config["average"] == 62 and b.is_bot
    assert competitors.custom_bot(db, 62, 30).id == b.id  # gleicher Bot -> Bilanz läuft weiter
    assert b in competitors.saved_bots(db) and b not in competitors.all_competitors(db)
    me = competitors.create_guest(db, "Me").id
    g = service.create_game(db, 301, 1, [me, b.id], None)
    service.add_visit(db, g, 26, None, 0)
    assert len(g.visits) == 2 and g.visits[1].competitor_id == b.id  # eigener Bot wirft auch
    # Profil eines Spielers: Average, Doppelquote geschätzt (keine Dart-für-Dart-Daten)
    a = competitors.create_guest(db, "Anna").id
    assert player_profile(db, a) is None
    x = competitors.create_guest(db, "X").id
    g2 = service.create_game(db, 301, 1, [a, x], None)
    for i, (sc, d) in enumerate(((180, None), (0, None), (121, 3))):
        service.add_visit(db, g2, sc, d, i)
    prof = player_profile(db, a)
    assert prof["average"] == pytest.approx(150.5) and prof["estimated"] and prof["games"] == 1
    # Mit Dart-für-Dart-Daten wird die echte Doppelquote genommen
    g3 = service.create_game(db, 301, 1, [a, x], None)
    service.add_visit(db, g3, None, None, 0, throws=["T20", "T20", "T20"])
    service.add_visit(db, g3, 0, None, 1)
    service.add_visit(db, g3, None, None, 2, throws=["T20", "T7", "S20"])  # 121 -> 20 Rest
    for i in range(3, 9, 2):
        service.add_visit(db, g3, 0, None, i)
        service.add_visit(db, g3, None, None, i + 1, throws=["M", "M", "M"]) if i < 7 else \
            service.add_visit(db, g3, None, None, i + 1, throws=["M", "M", "D10"])
    assert g3.status == "finished"
    full = player_profile(db, a)
    assert not full["estimated"] and full["double"] == pytest.approx(10)  # 10 Darts aufs Doppel (S20 bei 40 + 9 bei 20), 1 Treffer
    last1 = player_profile(db, a, last=1)
    assert last1["games"] == 1 and last1["average"] < full["average"]


@pytest.fixture
def olli2(db, make_user):
    make_user("olli")
    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        yield c


def test_web_custom_and_player_bots(olli2, db, seeded):
    me = competitors.competitor_for_user(db, db.scalar(select(models.User))).id
    form = olli2.get("/darts/new?bot=custom").text
    assert 'value="bot:custom"' in form and 'value="bot:player"' in form and 'name="bot_avg"' in form
    r = olli2.post("/darts/new", data={"mode": "x01", "start": 301, "legs": 1, "p0": str(me), "p1": "bot:custom",
                                       "bot_avg": "70", "bot_dbl": "35"}, follow_redirects=False)
    assert r.status_code == 303
    bot = db.scalar(select(models.Competitor).where(models.Competitor.name == "Bot 70 avg · 35%"))
    assert bot and bot.bot_config["double"] == 35
    # Bot wie ich selbst - geht erst, wenn ich Stats habe
    r = olli2.post("/darts/new", data={"mode": "x01", "start": 301, "legs": 1, "p0": str(me), "p1": "bot:player",
                                       "bot_like": str(me), "bot_basis": "last10"})
    assert r.status_code == 400 and "no finished X01 games" in r.text
    x = competitors.create_guest(db, "Sparring").id
    g = service.create_game(db, 301, 1, [me, x], None)
    for i, (sc, d) in enumerate(((100, None), (0, None), (100, None), (0, None), (101, 3))):
        service.add_visit(db, g, sc, d, i)
    assert "olli (you) · avg" in olli2.get("/darts/new?bot=player").text
    r = olli2.post("/darts/new", data={"mode": "x01", "start": 301, "legs": 1, "p0": str(me), "p1": "bot:player",
                                       "bot_like": str(me), "bot_basis": "last10"}, follow_redirects=False)
    assert r.status_code == 303
    mine = db.scalar(select(models.Competitor).where(models.Competitor.name == "Bot olli (last 10)"))
    assert mine.bot_config["like"] == me and mine.bot_config["basis"] == "last10"
    assert mine.bot_config["average"] == round(3 * 301 / 9)
    # Gespeicherte Bots stehen im Formular, die Bot-Seite beschreibt den Bot
    assert f'value="{mine.id}"' in olli2.get("/darts/new").text
    page = olli2.get(f"/darts/players/{mine.id}").text
    assert "copied from the last 10 games" in page and f"bot_id={mine.id}" in page
    assert f'"{mine.id}"' in olli2.get(f"/darts/new?bot_id={mine.id}").text  # vorausgewählt


def test_caller_data_on_page(olli2, db, seeded):
    me = competitors.competitor_for_user(db, db.scalar(select(models.User))).id
    r = olli2.post("/darts/new", data={"mode": "x01", "start": 301, "legs": 2, "p0": str(me), "p1": "bot:easy"},
                   follow_redirects=False)
    gid = int(r.headers["location"].rsplit("/", 1)[1])
    page = olli2.get(f"/darts/games/{gid}").text
    assert '"leg": 1' in page and '"match": false' in page and '"req": null' in page and '"call": null' in page
    olli2.post(f"/darts/games/{gid}/visit", data={"seq": 0, "score": 180})
    page = olli2.get(f"/darts/games/{gid}").text
    # Bot hat geworfen -> wird angesagt; ich stehe auf 121 -> "olli, you require 121"
    assert '"name": "Easy Bot"' in page and '"req": {"name": "olli", "rest": 121}' in page
    assert 'x-data="callerSettings"' in page and "Caller settings" in page
