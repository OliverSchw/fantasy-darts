"""Spiele bestätigen: Einstellung pro Account, offene Spiele zählen nicht, Bestätigen/Ablehnen, Turniere."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import beerpong as bp
from app import competitors, confirmations, models, push
from app import tournaments as tour
from app.darts import service
from app.darts.achievements import compute_achievements
from app.darts.rating import compute_elo
from app.darts.stats import compute_stats
from app.main import app


@pytest.fixture
def outbox():
    push.outbox = []
    yield push.outbox
    push.outbox = None


@pytest.fixture
def people(db, make_user):
    anna, ben = make_user("anna"), make_user("ben")
    ben.confirm_games = True
    db.commit()
    for u in (anna, ben):
        push.save_subscription(db, u, {"endpoint": f"https://push.example.com/{u.username}",
                                       "keys": {"p256dh": "B" + "A" * 86, "auth": "A" * 22}})
    return anna, ben, competitors.competitor_for_user(db, anna).id, competitors.competitor_for_user(db, ben).id


def _win(db, g):
    for i, (sc, d) in enumerate(((180, None), (0, None), (121, 3))):
        service.add_visit(db, g, sc, d, i)


def test_pending_game_does_not_count_until_confirmed(db, people, outbox):
    anna, ben, a, b = people
    g = service.create_game(db, 301, 1, [b, a], anna)  # Anna legt an, Ben wirft zuerst
    rows = confirmations.pending_for(db, ben)
    assert [(r.kind, r.ref_id) for r in rows] == [("darts", g.id)] and rows[0].added_by_id == anna.id
    assert not confirmations.pending_for(db, anna)  # wer anlegt, muss nicht bestätigen
    assert any(o["user_id"] == ben.id and o["url"] == "/confirm" for o in outbox)
    _win(db, g)  # Ben gewinnt mit 180 + 121
    st = compute_stats(db)
    assert b not in st and st[a].games == 1  # für Ben zählt es noch nicht, für Anna schon
    assert b not in compute_elo(db).ratings and a not in compute_elo(db).ratings  # Elo erst, wenn alle bestätigt haben
    assert b not in compute_achievements(db)
    assert confirmations.accept(db, ben, "darts", g.id)
    st = compute_stats(db)
    assert st[b].max180 == 1 and st[b].wins == 1
    assert compute_elo(db).rating(b) > 1000
    assert "ton80" in {e.key for e in compute_achievements(db)[b]}


def test_decline_replaces_with_guest(db, people):
    anna, ben, a, b = people
    g = service.create_game(db, 301, 1, [b, a], anna)
    _win(db, g)
    assert confirmations.decline(db, ben, "darts", g.id)
    db.expire_all()
    g = db.get(models.DartsGame, g.id)
    guest = g.players[0].competitor
    assert guest.name == "ben (guest)" and guest.is_guest
    assert {v.competitor_id for v in g.visits if v.position == 0} == {guest.id} and g.winner_id == guest.id
    assert b not in compute_stats(db) and compute_stats(db)[a].games == 1  # Annas Spiel bleibt
    assert not confirmations.pending_for(db, ben)
    # nochmal ablehnen: derselbe Gast wird wiederverwendet
    g2 = service.create_game(db, 301, 1, [b, a], anna)
    confirmations.decline(db, ben, "darts", g2.id)
    db.expire_all()
    assert db.get(models.DartsGame, g2.id).players[0].competitor_id == guest.id


def test_setting_off_and_self_created(db, people):
    anna, ben, a, b = people
    ben.confirm_games = False
    db.commit()
    service.create_game(db, 301, 1, [a, b], anna)
    assert not confirmations.pending_for(db, ben)  # ohne Einstellung zählt alles sofort
    ben.confirm_games = True
    db.commit()
    service.create_game(db, 301, 1, [a, b], ben)  # selbst angelegt
    assert not confirmations.pending_for(db, ben)
    bot = competitors.bot(db, "easy").id
    service.create_game(db, 301, 1, [b, bot], anna)
    assert len(confirmations.pending_for(db, ben)) == 1


def test_tournament_confirmation(db, people):
    anna, ben, a, b = people
    c = competitors.create_guest(db, "Carl").id
    t = tour.create_tournament(db, "darts", "Cup", [[a], [b], [c]], {"start": 301, "legs": 1, "final_legs": 1}, anna)
    rows = confirmations.pending_for(db, ben)
    assert [(r.kind, r.ref_id) for r in rows] == [("tournament", t.id)]
    # Spiele im Turnier fragen nicht extra nach, zählen aber erst nach der Turnier-Bestätigung
    m = next(m for m in t.matches if m.entry1 and m.entry2 and b in {x.competitor_id for x in m.entry1.members + m.entry2.members})
    g = service.start_tournament_game(db, t, m, anna)
    assert len(confirmations.pending_for(db, ben)) == 1
    assert (g.id, b) in confirmations.pending_pairs(db)
    # Ben bestätigt das Spiel -> gilt für das ganze Turnier
    assert confirmations.accept(db, ben, "darts", g.id)
    assert not confirmations.pending_for(db, ben) and not confirmations.pending_pairs(db)


def test_tournament_decline_and_hall_of_fame(db, people):
    anna, ben, a, b = people
    t = tour.create_tournament(db, "darts", "Final", [[b], [a]], {"start": 301, "legs": 1, "final_legs": 1}, anna)
    final = t.matches[0]
    g = service.start_tournament_game(db, t, final, anna)
    first = g.players[0].competitor_id
    for i, (sc, d) in enumerate(((180, None), (0, None), (121, 3))):
        service.add_visit(db, g, sc, d, i)
    db.refresh(t)
    winner_is_ben = first == b
    fame = dict((c.id, n) for c, n in tour.hall_of_fame(db, "darts"))
    if winner_is_ben:
        assert b not in fame  # Titel zählt erst nach der Bestätigung
    confirmations.decline(db, ben, "tournament", t.id)
    db.expire_all()
    t = db.get(models.Tournament, t.id)
    members = {mm.competitor.display_name for e in t.entries for mm in e.members}
    assert members == {"anna", "ben (guest)"}
    assert b not in {p.competitor_id for p in db.get(models.DartsGame, g.id).players}


def test_beerpong_pending(db, people):
    anna, ben, a, b = people
    g = bp.create_game(db, 6, [a], [b], anna)
    assert [(r.kind, r.ref_id) for r in confirmations.pending_for(db, ben)] == [("beerpong", g.id)]
    bp.set_final_score(db, g, 6, 3)
    assert b not in bp.compute_stats(db) and bp.compute_stats(db)[a].games == 1
    confirmations.accept(db, ben, "beerpong", g.id)
    assert bp.compute_stats(db)[b].games == 1


def _client(name):
    c = TestClient(app)
    c.__enter__()
    c.post("/login", data={"username": name, "password": "secret123"})
    return c


def test_web_flow(db, people):
    anna, ben, a, b = people
    ca, cb = _client("anna"), _client("ben")
    try:
        assert "Confirm games, tournaments and leagues" in cb.get("/account").text
        r = ca.post("/darts/new", data={"mode": "x01", "start": 301, "legs": 1, "p0": str(a), "p1": str(b),
                                        "scoring": "own"}, follow_redirects=False)
        gid = int(r.headers["location"].rsplit("/", 1)[1])
        home = cb.get("/").text
        assert "You were added to 1 game" in home
        page = cb.get(f"/darts/games/{gid}").text
        assert "added you to this game" in page and "Yes, that's me" in page
        assert "added you" not in ca.get(f"/darts/games/{gid}").text
        lst = cb.get("/confirm").text
        assert "Darts 301" in lst and "added by anna" in lst
        # Ben trägt seine eigene Aufnahme ein -> automatisch bestätigt
        ca.post(f"/darts/games/{gid}/visit", data={"seq": 0, "score": 60})
        cb.post(f"/darts/games/{gid}/visit", data={"seq": 1, "score": 45})
        assert not confirmations.pending_for(db, ben)
        assert "You were added" not in cb.get("/").text
        # Ablehnen über die Seite
        r = ca.post("/darts/new", data={"mode": "x01", "start": 301, "legs": 1, "p0": str(a), "p1": str(b)},
                    follow_redirects=False)
        gid2 = int(r.headers["location"].rsplit("/", 1)[1])
        r = cb.post(f"/confirm/darts/{gid2}/decline?next=/confirm")
        assert "replaced by a guest" in r.text
        db.expire_all()
        assert db.get(models.DartsGame, gid2).players[1].competitor.name == "ben (guest)"
        # Einstellung aus -> alles Offene zählt sofort
        ca.post("/darts/new", data={"mode": "x01", "start": 301, "legs": 1, "p0": str(a), "p1": str(b)})
        assert confirmations.pending_for(db, ben)
        cb.post("/account/confirm-games", data={})
        db.expire_all()
        assert not db.get(models.User, ben.id).confirm_games and not confirmations.pending_for(db, ben)
        assert cb.post("/confirm/nope/1/accept").status_code == 404
    finally:
        ca.__exit__(None, None, None)
        cb.__exit__(None, None, None)
