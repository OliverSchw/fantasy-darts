"""Darts-Bereich über die Web-Oberfläche."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.darts.stats import compute_stats
from app.main import app


def _login(name):
    c = TestClient(app)
    c.__enter__()
    assert c.post("/login", data={"username": name, "password": "secret123"}, follow_redirects=False).status_code == 303
    return c


@pytest.fixture
def olli(db, make_user):
    make_user("olli")
    c = _login("olli")
    yield c
    c.__exit__(None, None, None)


def _cid(db, name):
    db.expire_all()
    u = db.scalar(select(models.User).where(models.User.username == name))
    return db.scalar(select(models.Competitor).where(models.Competitor.user_id == u.id)).id


def _new_game(c, db, start=301, legs=1, players=("olli",), guest=None):
    data = {"start": start, "legs": legs}
    i = 0
    for i, name in enumerate(players):
        c.get("/darts")  # legt Teilnehmer für Konten an
        data[f"p{i}"] = _cid(db, name)
    if guest:
        data[f"p{len(players)}"] = "guest"
        data[f"g{len(players)}"] = guest
    r = c.post("/darts/new", data=data, follow_redirects=False)
    assert r.status_code == 303, r.text[:500]
    db.expire_all()
    return db.get(models.DartsGame, int(r.headers["location"].rsplit("/", 1)[1]))


def _visit(c, game, score, darts=None, seq=None):
    data = {"score": score, "seq": len(game.visits) if seq is None else seq}
    if darts:
        data["darts"] = darts
    return c.post(f"/darts/games/{game.id}/visit", data=data)


def test_login_required(client=None):
    with TestClient(app) as guest:
        assert guest.get("/darts", follow_redirects=False).status_code == 303


def test_full_game_with_guest(olli, db):
    game = _new_game(olli, db, start=301, legs=1, guest="Kevin")
    assert [p.competitor.display_name for p in game.players] == ["olli", "Kevin"]
    page = olli.get(f"/darts/games/{game.id}").text
    assert "olli</a>" in page and "Kevin" in page and "to throw" in page

    for score in (180, 100):  # olli 121, Kevin 201
        _visit(olli, game, score); db.refresh(game)
    assert "T20 · T11 · D14" in olli.get(f"/darts/games/{game.id}").text or "Checkout 121" in olli.get(f"/darts/games/{game.id}").text
    r = _visit(olli, game, 121)  # ohne Darts-Angabe
    assert "How many darts" in r.text
    db.refresh(game)
    _visit(olli, game, 121, darts=3); db.refresh(game)
    assert game.status == "finished" and game.winner.display_name == "olli"
    assert "wins" in olli.get(f"/darts/games/{game.id}").text

    stats = compute_stats(db)
    me = stats[_cid(db, "olli")]
    assert me.wins == 1 and me.games == 1 and me.max180 == 1 and me.high_finish == 121
    assert me.darts == 6 and round(me.average, 1) == 150.5 and me.best_leg == 6  # 180 + 121 in 3 Darts
    kevin = next(s for cid, s in stats.items() if cid != _cid(db, "olli"))
    assert kevin.games == 1 and kevin.wins == 0 and kevin.tons == 1


def test_bust_and_impossible(olli, db):
    game = _new_game(olli, db, start=301)
    _visit(olli, game, 180); db.refresh(game)  # Rest 121
    r = _visit(olli, game, 179)
    assert "not possible" in r.text
    db.refresh(game)
    r = _visit(olli, game, 140)  # 121 - 140 -> Bust
    assert "Bust" in r.text
    db.refresh(game)
    assert game.visits[-1].bust and game.visits[-1].score == 0


def test_double_submit_is_ignored(olli, db):
    game = _new_game(olli, db)
    _visit(olli, game, 60, seq=0)
    r = _visit(olli, game, 60, seq=0)  # gleiche Eingabe nochmal (Doppel-Tipp)
    assert "updated in the meantime" in r.text
    db.refresh(game)
    assert len(game.visits) == 1


def test_undo_reopens_finished_game(olli, db):
    game = _new_game(olli, db, start=301)
    for s in (180, 81):
        _visit(olli, game, s); db.refresh(game)
    _visit(olli, game, 40, darts=1); db.refresh(game)
    assert game.status == "finished"
    olli.post(f"/darts/games/{game.id}/undo"); db.refresh(game)
    assert game.status == "live" and len(game.visits) == 2 and game.winner_id is None


def test_permissions(olli, db, make_user):
    make_user("anna")
    make_user("boss", admin=True)
    game = _new_game(olli, db)
    anna = _login("anna")
    assert anna.post(f"/darts/games/{game.id}/visit", data={"score": 60, "seq": 0}).status_code == 403
    assert anna.post(f"/darts/games/{game.id}/abandon").status_code == 403
    assert "OK</button>" not in anna.get(f"/darts/games/{game.id}").text  # nur Zuschauen
    boss = _login("boss")
    assert boss.post(f"/darts/games/{game.id}/visit", data={"score": 60, "seq": 0}, follow_redirects=False).status_code == 303
    v = anna.get(f"/darts/games/{game.id}/version").json()
    assert v == {"v": 1, "status": "live"}


def test_abandoned_games_dont_count(olli, db):
    game = _new_game(olli, db)
    _visit(olli, game, 180)
    olli.post(f"/darts/games/{game.id}/abandon")
    db.refresh(game)
    assert game.status == "abandoned"
    assert compute_stats(db) == {}
    assert olli.post(f"/darts/games/{game.id}/visit", data={"score": 60, "seq": 1}).status_code == 403


def test_new_game_validation(olli, db, make_user):
    make_user("kevin")
    olli.get("/darts")
    me = _cid(db, "olli")
    r = olli.post("/darts/new", data={"start": 501, "legs": 1, "p0": me, "p1": me})
    assert r.status_code == 400 and "only take part once" in r.text
    r = olli.post("/darts/new", data={"start": 501, "legs": 1, "p0": me, "p1": "guest", "g1": "Kevin"})
    assert r.status_code == 400 and "already exists" in r.text  # Gastname = Username
    r = olli.post("/darts/new", data={"start": 999, "legs": 1, "p0": me})
    assert r.status_code == 400


def test_pages_render(olli, db):
    game = _new_game(olli, db, players=("olli",), guest="Kevin")
    _visit(olli, game, 100)
    for url in ("/darts", "/darts/new", "/darts/games", "/darts/players", f"/darts/players/{_cid(db, 'olli')}",
                f"/darts/games/{game.id}", "/"):
        assert olli.get(url).status_code == 200, url
    assert "LIVE" in olli.get("/darts").text and "1 game running" in olli.get("/").text
    me = db.scalar(select(models.User).where(models.User.username == "olli"))
    assert "🎯 Darts" in olli.get(f"/users/{me.id}").text


def test_admin_links_guest_to_account(olli, db, make_user):
    game = _new_game(olli, db, guest="Kevin")
    _visit(olli, game, 60); db.refresh(game); _visit(olli, game, 140)
    kevin_guest = next(p.competitor for p in game.players if p.competitor.is_guest)
    kev = make_user("kev")
    make_user("boss", admin=True)
    boss = _login("boss")
    boss.get("/darts")  # kev bekommt einen (leeren) Teilnehmer
    assert "Link guest to an account" in boss.get(f"/darts/players/{kevin_guest.id}").text
    assert olli.post(f"/darts/players/{kevin_guest.id}/link", data={"user_id": kev.id}).status_code == 403
    boss.post(f"/darts/players/{kevin_guest.id}/link", data={"user_id": kev.id})
    db.expire_all()
    c = db.scalar(select(models.Competitor).where(models.Competitor.user_id == kev.id))
    assert c.id == kevin_guest.id and c.display_name == "kev"
    assert compute_stats(db)[c.id].ton40 == 1  # Stats sind mitgewandert


def test_doubles_game(olli, db, make_user):
    for n in ("anna", "ben", "cleo"):
        make_user(n)
    olli.get("/darts/new")  # legt Teilnehmer für alle Mitglieder an
    ids = [_cid(db, n) for n in ("olli", "anna", "ben", "cleo")]  # T1: olli+ben, T2: anna+cleo
    r = olli.post("/darts/new", data={"start": 301, "legs": 1, "team_size": 2,
                                      "p0": ids[0], "p1": ids[1], "p2": ids[2], "p3": ids[3]}, follow_redirects=False)
    assert r.status_code == 303, r.text[:300]
    game = db.get(models.DartsGame, int(r.headers["location"].rsplit("/", 1)[1]))
    assert game.team_size == 2 and game.side_name(0) == "olli & ben" and game.side_name(1) == "anna & cleo"
    page = olli.get(f"/darts/games/{game.id}").text
    assert "olli &amp; ben" in page and "olli throws" in page
    # Reihenfolge: olli 180 (T1 Rest 121), anna 60, ben 81 (T1 Rest 40), cleo 60, olli checkt 40
    for score, darts in ((180, None), (60, None), (81, None), (60, None), (40, 2)):
        _visit(olli, game, score, darts); db.refresh(game)
    assert game.status == "finished" and game.winning_side == 0
    assert "olli &amp; ben" in olli.get("/darts").text
    stats = compute_stats(db)
    assert stats[ids[0]].wins == 1 and stats[ids[2]].wins == 1  # beide im Siegerteam
    assert stats[ids[1]].wins == 0 and stats[ids[1]].games == 1
    from app.darts.stats import head_to_head
    assert head_to_head(db, ids[0], ids[2]).game_ids == []  # Partner sind keine Gegner
    h = head_to_head(db, ids[0], ids[1])
    assert (h.wins_a, h.wins_b) == (1, 0)
    # Doppel braucht genau 4 Spieler
    r = olli.post("/darts/new", data={"start": 301, "legs": 1, "team_size": 2, "p0": ids[0], "p1": ids[1], "p2": ids[2]})
    assert r.status_code == 400 and "exactly 4" in r.text
