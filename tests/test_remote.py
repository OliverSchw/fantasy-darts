"""Jeder zählt selbst ("Own phones"): nur eigene Aufnahmen eintragen/zurücknehmen, Gäste zählt der Ersteller."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import competitors, models
from app.darts import service
from app.main import app


def _login(name):
    c = TestClient(app)
    c.__enter__()
    c.post("/login", data={"username": name, "password": "secret123"})
    return c


@pytest.fixture
def two(db, make_user):
    a, b = make_user("anna"), make_user("ben")
    ca, cb = _login("anna"), _login("ben")
    yield a, b, ca, cb
    ca.__exit__(None, None, None)
    cb.__exit__(None, None, None)


def _cid(db, user):
    return competitors.competitor_for_user(db, user).id


def test_own_scoring_rules(db, two):
    a, b, _, _ = two
    guest = competitors.create_guest(db, "Gast").id
    g = service.create_game(db, 501, 1, [_cid(db, a), _cid(db, b), guest], a, scoring="own")
    assert g.own_scoring
    assert service.can_score(a, g) and not service.can_score(b, g)  # Anna ist dran
    service.add_visit(db, g, 60, None, 0)
    assert service.can_score(b, g) and not service.can_score(a, g)  # jetzt Ben
    assert service.can_undo(a, g) and not service.can_undo(b, g)  # nur die eigene Aufnahme zurücknehmen
    service.add_visit(db, g, 45, None, 1)
    assert service.can_score(a, g) and not service.can_score(b, g)  # Gast: zählt die Erstellerin Anna
    assert service.can_undo(b, g) and not service.can_undo(a, g)
    # ein Handy für alle (Standard): jeder Mitspieler darf alles
    g2 = service.create_game(db, 501, 1, [_cid(db, a), _cid(db, b)], a)
    assert not g2.own_scoring and service.can_score(b, g2) and service.can_score(a, g2)


def test_own_scoring_party_game(db, two):
    a, b, _, _ = two
    g = service.create_mode_game(db, "atc", [_cid(db, a), _cid(db, b)], a, scoring="own")
    assert service.can_score(a, g) and not service.can_score(b, g)
    service.add_mode_visit(db, g, ["S1", "S2", "M"], 0)
    assert service.can_score(b, g) and not service.can_score(a, g)


def test_web_remote_game(db, two):
    a, b, ca, cb = two
    r = ca.post("/darts/new", data={"mode": "x01", "start": 501, "legs": 1, "p0": str(_cid(db, a)),
                                    "p1": str(_cid(db, b)), "scoring": "own"}, follow_redirects=False)
    gid = int(r.headers["location"].rsplit("/", 1)[1])
    g = db.get(models.DartsGame, gid)
    assert g.scoring == "own"
    page_a, page_b = ca.get(f"/darts/games/{gid}").text, cb.get(f"/darts/games/{gid}").text
    assert 'class="dg-pad"' in page_a and "🌍 own phones" in page_a
    assert 'class="dg-pad"' not in page_b and "anna</strong>'s turn" in page_b
    # Ben darf nicht für Anna eintragen
    assert cb.post(f"/darts/games/{gid}/visit", data={"seq": 0, "score": 60}).status_code == 403
    ca.post(f"/darts/games/{gid}/visit", data={"seq": 0, "score": 100})
    page_b = cb.get(f"/darts/games/{gid}").text
    assert 'class="dg-pad"' in page_b and '"call": "anna, 100"' in page_b  # Ansager sagt Annas 100 an
    assert "Undo my last visit" in ca.get(f"/darts/games/{gid}").text
    assert "Undo" not in page_b  # Ben hat noch nichts geworfen
    assert cb.post(f"/darts/games/{gid}/undo").status_code == 403  # Annas Aufnahme darf Ben nicht zurücknehmen
    # Akku leer? Auf ein Handy für alle umschalten
    cb.post(f"/darts/games/{gid}/scoring")
    db.expire_all()
    assert db.get(models.DartsGame, gid).scoring is None
    assert 'class="dg-pad"' in ca.get(f"/darts/games/{gid}").text  # jetzt darf Anna auch für Ben zählen
    form = ca.get("/darts/new").text
    assert 'value="own"' in form and "Own phones" in form
