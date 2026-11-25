"""Training (Bob's 27, 121 Checkout) und X01 Dart für Dart mit Doppelquote."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import competitors, models
from app.darts import service
from app.darts.achievements import compute_achievements
from app.darts.engine import DartsError, new_state, play
from app.darts.modes import apply_visit, new_mode_state
from app.darts.rating import compute_elo
from app.darts.stats import compute_stats, mode_records, training_records
from app.darts.throws import double_attempts, is_double_out, x01_visit
from app.main import app

MISS = ["M", "M", "M"]


# ---------------------------------------------------------------- Bob's 27


def test_bobs27_scoring():
    s = new_mode_state("bobs27", 1)
    assert s.points == [27] and s.bobs_target(0) == 1
    apply_visit(s, ["D1", "D1", "M"])  # +4
    assert s.points == [31] and s.bobs_target(0) == 2
    apply_visit(s, MISS)  # -4
    assert s.points == [27]
    apply_visit(s, ["T3", "S3", "D3"])  # nur das Doppel zählt: +6
    assert s.points == [33]
    with pytest.raises(DartsError):
        apply_visit(s, ["D4"])  # immer 3 Darts
    for _ in range(17):  # D4 ... D20 alle daneben: 33 - 2*(4+...+20) < 0 -> irgendwann raus
        if s.finished:
            break
        apply_visit(s, MISS)
    assert s.finished and s.points[0] <= 0 and s.winner == 0


def test_bobs27_full_game_and_bull():
    s = new_mode_state("bobs27", 2)
    for r in range(1, 21):
        apply_visit(s, [f"D{r}", "M", "M"])  # Spieler 1 trifft immer einmal
        apply_visit(s, [f"D{r}", f"D{r}", "M"])  # Spieler 2 zweimal
    assert not s.finished and s.bobs_target(0) == 25
    apply_visit(s, ["DB", "M", "M"])
    apply_visit(s, MISS)
    total = sum(2 * r for r in range(1, 21))
    assert s.finished and s.points == [27 + total + 50, 27 + 2 * total - 50] and s.winner == 1


def test_bobs27_out_player_skipped():
    s = new_mode_state("bobs27", 2)
    for _ in range(6):  # Spieler 1: 27 - 2 - 4 - 6 - 8 - 10 < 0 -> raus
        apply_visit(s, MISS)
        apply_visit(s, ["D%d" % (s.rounds_done[1] + 1), "M", "M"])
        if not s.alive(0):
            break
    assert not s.alive(0) and s.turn == 1  # nur noch Spieler 2 wirft
    apply_visit(s, MISS)
    assert s.turn == 1


# ---------------------------------------------------------------- 121 Checkout


def test_checkout121_attempts():
    s = new_mode_state("checkout121", 2, {"attempts": 5})
    apply_visit(s, ["T20", "T19", "D2"])  # 121 in 3 Darts
    assert s.successes == [1, 0] and s.target[0] == 122 and s.turn == 1  # Versuch vorbei -> nächster
    apply_visit(s, ["T20", "S20", "M"])  # 41 übrig
    assert s.rest[1] == 41 and s.turn == 1  # gleicher Versuch, 2. Aufnahme
    with pytest.raises(DartsError):
        apply_visit(s, ["S20", "S20", "M"])  # nach dem Bust (1 übrig) kein Dart mehr
    apply_visit(s, ["S20", "S20"])  # 1 übrig = Bust -> Rest bleibt 41
    assert s.rest[1] == 41 and s.attempt_visits[1] == 2
    apply_visit(s, ["S1", "D20"])  # Checkout mit 2 Darts in der 3. Aufnahme
    assert s.successes[1] == 1 and s.target[1] == 122 and s.turn == 0
    # Fehlversuch: Ziel eins runter, aber nie unter 121
    for _ in range(3):
        apply_visit(s, MISS)
    assert s.target[0] == 121 and s.successes[0] == 1 and s.attempts[0] == 2
    with pytest.raises(DartsError):
        apply_visit(s, ["T20", "T20", "S1", "M"])
    with pytest.raises(DartsError):
        apply_visit(s, ["T20", "T20", "D1", "M"][:2])  # 2 Darts ohne Ende der Aufnahme
    with pytest.raises(DartsError):
        new_mode_state("checkout121", 1, {"attempts": 7})


def test_checkout121_not_on_double_is_bust():
    s = new_mode_state("checkout121", 1, {"attempts": 5})
    apply_visit(s, ["T20", "T19", "S4"])  # 121, aber nicht auf ein Doppel
    assert s.successes == [0] and s.rest == [121] and "bust" in s.log


def _route(rest):
    """Checkout-Vorschlag als Dart-Codes ("T20", "Bull" -> "DB", "25" -> "SB", "19" -> "S19")."""
    from app.darts.checkouts import checkout_route
    conv = {"Bull": "DB", "25": "SB"}
    return [conv.get(d, d if d[0] in "SDT" else "S" + d) for d in checkout_route(rest)]


def test_checkout121_game_end_winner():
    s = new_mode_state("checkout121", 2, {"attempts": 5})
    for _ in range(5):
        apply_visit(s, _route(s.rest[0]))  # Spieler 1 checkt jedes Mal (121, 122, 123 ...)
        for _ in range(3):
            apply_visit(s, MISS)
    assert s.finished and s.winner == 0 and s.successes == [5, 0] and s.best == [125, 0]
    assert s.target == [126, 121]


# ---------------------------------------------------------------- X01 Dart für Dart


def test_x01_visit_from_throws():
    st = new_state(301, 1, 2)
    v = x01_visit(st, ["T20", "T20", "T20"])
    assert (v.score, v.darts, v.bust, v.checkout) == (180, 3, False, False)
    play(st, 180)
    play(st, 0)
    v = x01_visit(st, ["T20", "T15", "D8"])  # 121
    assert v.checkout and v.darts == 3 and v.score == 121
    v = x01_visit(st, ["T20", "T20"])  # 1 übrig -> Bust, Aufnahme vorbei
    assert v.bust and v.score == 0
    with pytest.raises(DartsError):
        x01_visit(st, ["T20", "T20", "D1"])  # nach dem Bust kein Dart mehr
    v = x01_visit(st, ["T20", "T19", "S4"])
    assert v.bust  # 121 nicht auf ein Doppel
    st2 = new_state(301, 1, 2)
    for score in (180, 0, 81, 0):
        play(st2, score)
    v = x01_visit(st2, ["D20"])  # 40 Rest, mit einem Dart aus
    assert v.checkout and v.darts == 1
    with pytest.raises(DartsError):
        x01_visit(st2, ["D20", "S5"])  # nach dem Checkout kein Dart mehr
    with pytest.raises(DartsError):
        x01_visit(st2, ["S5"])  # Aufnahme nicht vorbei
    v = x01_visit(st2, ["S19", "S20"])  # 1 Rest -> Bust
    assert v.bust


def test_double_attempts():
    assert is_double_out(40) and is_double_out(50) and is_double_out(2)
    assert not is_double_out(41) and not is_double_out(42) and not is_double_out(1)
    assert double_attempts(40, ["D20"]) == (1, 1)
    assert double_attempts(40, ["S20", "D10"]) == (2, 1)  # 40 -> 20, beides Doppel-Reste
    assert double_attempts(40, ["S1", "S1", "S2"]) == (2, 0)  # bei 40 und 38 (39 ist ungerade)
    assert double_attempts(100, ["T20", "D20"]) == (1, 1)
    assert double_attempts(32, ["D8", "D8"]) == (2, 1)  # 32 -> 16 -> D8 trifft
    assert double_attempts(50, ["SB", "D5", "M"]) == (1, 0)  # Bull verfehlt (25 getroffen), danach ungerade Reste
    assert double_attempts(50, ["S10", "D20"]) == (1, 1)  # S10 bei 50 ist kein Versuch, D20 bei 40 trifft
    assert double_attempts(50, ["DB"]) == (1, 1)
    assert double_attempts(60, None) == (0, 0)


def _guests(db, *names):
    return [competitors.create_guest(db, n).id for n in names]


def test_service_stats_and_achievements(db):
    a, b = _guests(db, "A", "B")
    g = service.create_game(db, 301, 1, [a, b], None)
    service.add_visit(db, g, None, None, 0, throws=["T20", "T20", "T20"])
    service.add_visit(db, g, 60, None, 1)  # Gesamt-Eingabe geht weiter
    service.add_visit(db, g, None, None, 2, throws=["T20", "S11", "S10"])  # 81 -> 40 Rest
    service.add_visit(db, g, 0, None, 3)
    service.add_visit(db, g, None, None, 4, throws=["S20", "D5", "D10"])  # 40 -> 20 -> 10, D10 = 20 -> Bust
    assert g.visits[-1].bust and g.visits[-1].throws == ["S20", "D5", "D10"]
    service.add_visit(db, g, 0, None, 5)
    service.add_visit(db, g, None, None, 6, throws=["D20"])
    assert g.status == "finished" and g.visits[-1].darts == 1
    st = compute_stats(db)[a]
    # Doppel-Versuche: Aufnahme 5: 40 (1), 20 (1, D5 statt D10), 10 (1, D10 -> 20 Bust); Aufnahme 7: 40 (1, Treffer)
    assert (st.double_darts, st.double_hits) == (4, 1) and st.double_pct == 25
    assert st.average == pytest.approx(3 * 301 / 10)  # 3 + 3 + 3 (Bust) + 1 Darts
    got = {e.key for e in compute_achievements(db)[a]}
    assert "ton80" in got and "first_win" in got
    # Bull-Finish wird jetzt am Dart erkannt
    g2 = service.create_game(db, 301, 1, [b, a], None)
    for i, t in enumerate((["T20"] * 3, ["M"] * 3, ["T20", "S11", "M"], ["M"] * 3, ["DB"])):  # 50 Rest -> Bull
        service.add_visit(db, g2, None, None, i, throws=list(t))
    assert g2.status == "finished"
    assert "bull_finish" in {e.key for e in compute_achievements(db)[b]}


def test_training_not_in_elo_or_wins(db):
    a, b = _guests(db, "A", "B")
    g = service.create_mode_game(db, "checkout121", [a, b], None, {"attempts": 5})
    seq = 0
    for _ in range(5):
        service.add_mode_visit(db, g, ["T20", "T19", "D2"] if seq == 0 or g.visits[-1].position == 1 and False else MISS, seq)
        seq += 1
        while g.status == "live" and service.mode_state(g).turn == 1:
            service.add_mode_visit(db, g, MISS, seq)
            seq += 1
        if g.status != "live":
            break
    while g.status == "live":
        service.add_mode_visit(db, g, MISS, seq)
        seq += 1
    assert g.status == "finished" and g.winning_side == 0
    assert a not in compute_elo(db).ratings
    assert "first_win" not in {e.key for e in compute_achievements(db).get(a, [])}
    assert mode_records(db, [a]) == {}
    rec = training_records(db, a)["checkout121"]
    assert rec["games"] == 1 and rec["hits"] == 1 and rec["attempts"] == 5 and rec["highest"] == 121
    b27 = service.create_mode_game(db, "bobs27", [a], None)
    for i in range(30):
        if b27.status != "live":
            break
        service.add_mode_visit(db, b27, MISS, i)
    assert b27.status == "finished"
    assert training_records(db, a)["bobs27"]["best"] <= 0


@pytest.fixture
def olli(db, make_user):
    make_user("olli")
    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        yield c


def test_web_flow(olli, db):
    me = competitors.competitor_for_user(db, db.scalar(select(models.User))).id
    form = olli.get("/darts/new?mode=bobs27").text
    assert "Training" in form and "Bob&#39;s 27" in form
    r = olli.post("/darts/new", data={"mode": "checkout121", "attempts": "5", "p0": str(me)}, follow_redirects=False)
    gid = int(r.headers["location"].rsplit("/", 1)[1])
    page = olli.get(f"/darts/games/{gid}").text
    assert "121 Checkout" in page and "attempt 1/5" in page and "T20 · T15 · D8" in page
    r = olli.post(f"/darts/games/{gid}/throws", data={"seq": 0, "throws": "T20,T19,D2"})
    assert db.get(models.DartsGame, gid).visits[0].checkout
    assert "Checkout!" in r.text and "attempt 2/5" in r.text and "122 left" in r.text.replace("<strong>", "").replace("</strong>", "")
    # Turniere bieten kein Training an und lehnen es ab
    tform = olli.get("/darts/tournaments/new").text
    assert "checkout121" not in tform and "bobs27" not in tform
    # X01 Dart für Dart übers Formular
    r = olli.post("/darts/new", data={"mode": "x01", "start": 301, "legs": 1, "p0": str(me)}, follow_redirects=False)
    xid = int(r.headers["location"].rsplit("/", 1)[1])
    assert "Dart by dart" in olli.get(f"/darts/games/{xid}").text
    olli.post(f"/darts/games/{xid}/visit", data={"seq": 0, "throws": "T20,T20,T20"})
    olli.post(f"/darts/games/{xid}/visit", data={"seq": 1, "throws": "T20,T20"})  # 121 -> 1 Rest = Bust
    g = db.get(models.DartsGame, xid)
    assert [v.score for v in g.visits] == [180, 0] and g.visits[1].bust
    r = olli.post(f"/darts/games/{xid}/visit", data={"seq": 2, "throws": "T20,X9"}, follow_redirects=True)
    assert "not a valid dart" in r.text
    for seq in range(1, 13):  # 121-Spiel zu Ende spielen (4 Fehlversuche à 3 Aufnahmen)
        olli.post(f"/darts/games/{gid}/throws", data={"seq": seq, "throws": "M,M,M"})
    assert db.get(models.DartsGame, gid).status == "finished"
    # Spielerseite zeigt Training und (nach Checkout) die Doppelquote
    olli.post(f"/darts/games/{xid}/visit", data={"seq": 2, "throws": "T20,T19,D2"})
    p = olli.get(f"/darts/players/{me}").text
    assert "Training" in p and "121 checkouts" in p and "Doubles hit" in p
    assert "🏋️ Training" in olli.get("/darts").text


# ---------------------------------------------------------------- Gesamtpunktzahl + "Darts aufs Doppel?"


def test_max_and_ask_double_darts():
    from app.darts.throws import ask_double_darts, max_double_darts
    assert [max_double_darts(r) for r in (40, 50, 2, 41, 60, 100, 110, 130, 170, 3)] == [3, 3, 3, 2, 2, 2, 2, 1, 1, 2]
    assert ask_double_darts(140, 100, False, False) == 1  # 40 übrig - letzter Dart könnte aufs Doppel gegangen sein
    assert ask_double_darts(140, 60, False, False) == 0  # 80 übrig - kein Doppelversuch möglich
    assert ask_double_darts(32, 0, False, False) == 3
    assert ask_double_darts(32, 40, True, False) == 3  # Bust
    assert ask_double_darts(501, 180, False, False) == 0


def test_double_darts_with_visit_totals(db):
    a, b = (competitors.create_guest(db, n).id for n in ("A", "B"))
    g = service.create_game(db, 301, 1, [a, b], None)
    service.add_visit(db, g, 180, None, 0)
    service.add_visit(db, g, 0, None, 1)
    with pytest.raises(DartsError):  # von 121 aus geht höchstens 1 Dart aufs Doppel (erst zweimal vorlegen)
        service.add_visit(db, g, 81, None, 2, double_darts=3)
    service.add_visit(db, g, 81, None, 2, double_darts=0)  # 40 übrig, nichts aufs Doppel
    service.add_visit(db, g, 0, None, 3)
    service.add_visit(db, g, 0, None, 4, double_darts=3)  # dreimal D20 verfehlt
    service.add_visit(db, g, 0, None, 5)
    with pytest.raises(DartsError):
        service.add_visit(db, g, 40, 2, 6, double_darts=0)  # Checkout braucht mindestens einen Dart aufs Doppel
    with pytest.raises(DartsError):
        service.add_visit(db, g, 40, 2, 6, double_darts=3)  # mehr als geworfen
    service.add_visit(db, g, 40, 2, 6, double_darts=2)
    assert g.status == "finished"
    st = compute_stats(db)[a]
    assert (st.double_darts, st.double_hits) == (5, 1) and st.double_pct == 20
    # Angabe "keine Doppel-Darts möglich" wird abgelehnt
    g2 = service.create_game(db, 301, 1, [a, b], None)
    with pytest.raises(DartsError):
        service.add_visit(db, g2, 60, None, 0, double_darts=1)


def test_double_darts_web(olli, db):
    me = competitors.competitor_for_user(db, db.scalar(select(models.User))).id
    r = olli.post("/darts/new", data={"mode": "x01", "start": 301, "legs": 1, "p0": str(me)}, follow_redirects=False)
    gid = int(r.headers["location"].rsplit("/", 1)[1])
    assert "scorer(301, false, 0, 0)" in olli.get(f"/darts/games/{gid}").text  # bei 301 kein Doppel erreichbar
    olli.post(f"/darts/games/{gid}/visit", data={"seq": 0, "score": 180})
    assert "scorer(121, true, 3, 1)" in olli.get(f"/darts/games/{gid}").text
    r = olli.post(f"/darts/games/{gid}/visit", data={"seq": 1, "score": 81})  # Angabe fehlt -> Pflicht
    assert "How many darts went at the double" in r.text and len(db.get(models.DartsGame, gid).visits) == 1
    olli.post(f"/darts/games/{gid}/visit", data={"seq": 1, "score": 81, "double_darts": "1"})
    olli.post(f"/darts/games/{gid}/visit", data={"seq": 2, "score": 40, "darts": "1"})  # nur 1 möglich -> automatisch
    g = db.get(models.DartsGame, gid)
    assert [v.double_darts for v in g.visits] == [None, 1, 1] and g.status == "finished"
    r = olli.post("/darts/new", data={"mode": "x01", "start": 301, "legs": 1, "p0": str(me)}, follow_redirects=False)
    gid2 = int(r.headers["location"].rsplit("/", 1)[1])
    r = olli.post(f"/darts/games/{gid2}/visit", data={"seq": 0, "score": 0, "double_darts": "x"})
    assert r.status_code == 200 and "Please enter a number" in r.text and not db.get(models.DartsGame, gid2).visits
    r = olli.post(f"/darts/games/{gid2}/visit", data={"seq": 0, "score": 60, "double_darts": "1"})
    assert "No dart could have gone at a double" in r.text
