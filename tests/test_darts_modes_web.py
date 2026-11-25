"""Partyspiele über die Webseite."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.darts.stats import compute_stats, mode_records
from app.main import app


def _login(name):
    c = TestClient(app)
    c.__enter__()
    c.post("/login", data={"username": name, "password": "secret123"})
    return c


@pytest.fixture
def olli(db, make_user):
    make_user("olli")
    make_user("anna")
    c = _login("olli")
    c.get("/darts/new")
    yield c
    c.__exit__(None, None, None)


def _cid(db, name):
    db.expire_all()
    u = db.scalar(select(models.User).where(models.User.username == name))
    return db.scalar(select(models.Competitor).where(models.Competitor.user_id == u.id)).id


def _new(c, db, mode, players=("olli", "anna"), **extra):
    data = {"mode": mode, **{f"p{i}": _cid(db, n) for i, n in enumerate(players)}, **extra}
    r = c.post("/darts/new", data=data, follow_redirects=False)
    assert r.status_code == 303, r.text[:400]
    db.expire_all()
    return db.get(models.DartsGame, int(r.headers["location"].rsplit("/", 1)[1]))


def _throw(c, db, g, *darts):
    r = c.post(f"/darts/games/{g.id}/throws", data={"throws": ",".join(darts), "seq": len(g.visits)})
    db.refresh(g)
    return r


def test_cricket_game(olli, db):
    g = _new(olli, db, "cricket")
    assert g.mode == "cricket" and "Cricket" in olli.get(f"/darts/games/{g.id}").text
    for tgt in ("20", "19", "18", "17", "16", "15"):
        _throw(olli, db, g, f"T{tgt}", "M", "M")  # olli schließt
        _throw(olli, db, g, "M", "M", "M")  # anna daneben
    r = _throw(olli, db, g, "DB", "SB")  # Bull zu -> alles zu, 0:0 Punkte -> gewonnen mit 2 Darts
    assert g.status == "finished" and g.won_by(_cid(db, "olli")) and "wins Cricket" in r.text
    assert compute_stats(db) == {}  # X01-Stats bleiben leer
    assert mode_records(db, [_cid(db, "olli")])[_cid(db, "olli")]["cricket"] == (1, 1)
    page = olli.get(f"/darts/players/{_cid(db, 'olli')}").text
    assert "Party games" in page and "Cricket won" in page and "No X01 games yet" in page
    assert "Cricket" in olli.get("/darts/games").text


def test_atc_solo_and_validation(olli, db):
    g = _new(olli, db, "atc", players=("olli",))
    r = _throw(olli, db, g, "S1")
    assert "Enter all 3 darts" in r.text and len(g.visits) == 0
    _throw(olli, db, g, "S1", "S2", "T3")
    assert "target <strong>4</strong>" in olli.get(f"/darts/games/{g.id}").text
    # Falsche Route / ungültige Darts
    assert olli.post(f"/darts/games/{g.id}/visit", data={"score": 60, "seq": 1}).status_code == 400
    assert "not a valid dart" in _throw(olli, db, g, "T25", "M", "M").text
    # Undo
    olli.post(f"/darts/games/{g.id}/undo"); db.refresh(g)
    assert len(g.visits) == 0
    r = olli.post("/darts/new", data={"mode": "cricket", "p0": _cid(db, "olli")})
    assert r.status_code == 400 and "2–4 players" in r.text


def test_shanghai_instant_win(olli, db):
    g = _new(olli, db, "shanghai", rounds="7")
    r = _throw(olli, db, g, "S1", "D1", "T1")
    assert g.status == "finished" and "Shanghai!" in r.text


def test_killer_game(olli, db):
    g = _new(olli, db, "killer", lives="1")
    nums = g.options["numbers"]
    assert len(set(nums)) == 2 and g.options["lives"] == 1
    page = olli.get(f"/darts/games/{g.id}").text
    assert f"hit <strong>D{nums[0]}</strong>" in page
    r = _throw(olli, db, g, f"D{nums[0]}", f"D{nums[1]}")  # Killer + anna raus -> gewonnen
    assert g.status == "finished" and g.won_by(_cid(db, "olli")) and "Killer!" in r.text


def test_mode_permissions_and_live(olli, db, make_user):
    g = _new(olli, db, "atc", players=("olli",))
    make_user("zuschauer")
    z = _login("zuschauer")
    assert z.post(f"/darts/games/{g.id}/throws", data={"throws": "S1,M,M", "seq": 0}).status_code == 403
    assert "Save visit" not in z.get(f"/darts/games/{g.id}").text
    _throw(olli, db, g, "S1", "M", "M")
    assert z.get(f"/darts/games/{g.id}/version").json() == {"v": 1, "status": "live"}
    # Doppelt abgeschickt
    r = olli.post(f"/darts/games/{g.id}/throws", data={"throws": "S2,M,M", "seq": 0})
    assert "updated in the meantime" in r.text
