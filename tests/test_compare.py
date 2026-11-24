"""Spieler vergleichen: Darts (Stats + direkter Vergleich) und Beer Pong (gegeneinander / zusammen)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import beerpong as bp
from app import competitors as comp
from app import models
from app.darts import service as ds
from app.darts.stats import compare_rows, compute_stats, head_to_head
from app.main import app


@pytest.fixture
def setup(db, make_user):
    olli, anna = make_user("olli"), make_user("anna")
    a, b = comp.competitor_for_user(db, olli), comp.competitor_for_user(db, anna)
    kevin = comp.create_guest(db, "Kevin")
    # Darts: olli schlägt anna (301, 180 / 60 / 121 Checkout); anna spielt zusätzlich gegen Kevin
    g = ds.create_game(db, 301, 1, [a.id, b.id], olli)
    for score, darts in ((180, None), (60, None), (121, 3)):
        ds.add_visit(db, g, score, darts, len(g.visits))
    g2 = ds.create_game(db, 301, 1, [b.id, kevin.id], anna)
    for score, darts in ((100, None), (100, None), (100, None), (100, None), (101, 3)):
        ds.add_visit(db, g2, score, darts, len(g2.visits))
    # Beer Pong: einmal gegeneinander (anna gewinnt), einmal zusammen (gewonnen)
    x = bp.create_game(db, 6, [a.id], [b.id], olli)
    for _ in range(6):
        bp.add_hit(db, x, 2, 1, x.version)
    y = bp.create_game(db, 6, [a.id, b.id], [kevin.id], olli)
    for _ in range(6):
        bp.add_hit(db, y, 1, 1, y.version)
    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        yield c, a, b


def test_head_to_head_numbers(db, setup):
    c, a, b = setup
    h = head_to_head(db, a.id, b.id)
    assert len(h.game_ids) == 1 and (h.wins_a, h.wins_b) == (1, 0) and (h.legs_a, h.legs_b) == (1, 0)
    assert h.stats_a.high_finish == 121 and h.stats_b.games == 1
    stats = compute_stats(db, [a.id, b.id])
    rows = {r["label"]: r for r in compare_rows(stats[a.id], stats[b.id])}
    assert rows["3-dart average"]["winner"] == "a" and rows["Games played"]["winner"] is None
    assert rows["Best leg (darts)"]["winner"] == "a"  # weniger Darts ist besser
    r = bp.rivalry(db, a.id, b.id)
    assert (r.wins_a, r.wins_b, len(r.together), r.together_wins) == (0, 1, 1, 1)


def test_compare_pages(db, setup):
    c, a, b = setup
    page = c.get(f"/darts/compare?b={b.id}").text  # a = ich selbst
    assert "Head to head" in page and "legs 1 : 0" in page and "Categories won" in page
    assert 'class="cmp-v best"' in page
    page = c.get(f"/beerpong/compare?b={b.id}").text
    assert "Against each other" in page and "cups 0 : 6" in page and "1</strong> of <strong>1</strong> games won together" in page
    assert "Pick two different players" in c.get(f"/darts/compare?a={a.id}&b={a.id}").text
    assert "Pick two players" in c.get("/darts/compare").text
    assert c.get("/darts/compare?a=abc&b=999").status_code == 200  # Unsinn in der URL -> einfach leer
    assert f"/darts/compare?b={b.id}" in c.get(f"/darts/players/{b.id}").text
    assert f"/darts/compare?b={b.id}" in c.get(f"/users/{b.user_id}").text
    with TestClient(app) as guest:
        assert guest.get("/darts/compare", follow_redirects=False).status_code == 303
