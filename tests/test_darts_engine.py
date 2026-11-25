"""Darts-Spiellogik: Bust, Checkout, Legs, Anwurf-Wechsel, Checkout-Vorschläge."""

import pytest

from app.darts.checkouts import checkout_route, is_finishable, min_darts
from app.darts.engine import DartsError, Visit, advance, make_visit, new_state, play, replay


def test_checkout_routes():
    assert checkout_route(170) == ("T20", "T20", "Bull")
    assert checkout_route(100) == ("T20", "D20")
    assert checkout_route(40) == ("D20",)
    assert checkout_route(50) == ("Bull",)
    for bogey in (159, 162, 163, 165, 166, 168, 169, 171, 1, 0):
        assert not is_finishable(bogey), bogey
    assert min_darts(99) == 3 and min_darts(110) == 2 and min_darts(2) == 1
    # Jeder Vorschlag ergibt genau den Rest und endet auf einem Doppel
    value = {"Bull": 50, "25": 25}
    for rest in range(2, 171):
        route = checkout_route(rest)
        if route is None:
            continue
        total = 0
        for d in route:
            if d in value:
                total += value[d]
            elif d[0] in "DT":
                total += int(d[1:]) * (2 if d[0] == "D" else 3)
            else:
                total += int(d)
        assert total == rest and (route[-1].startswith("D") or route[-1] == "Bull"), (rest, route)


def test_normal_visit_and_turns():
    s = new_state(501, 1, 2)
    play(s, 60)
    assert s.remaining == [441, 501] and s.turn == 1
    play(s, 100)
    assert s.remaining == [441, 401] and s.turn == 0


@pytest.mark.parametrize("rest,score", [(40, 50), (40, 39), (159, 159), (2, 3)])
def test_bust(rest, score):
    s = new_state(301, 1, 1)
    s.remaining = [rest]
    v = play(s, score)
    assert v.bust and v.score == 0 and v.darts == 3 and s.remaining == [rest]


def test_impossible_scores_rejected():
    s = new_state(501, 1, 2)
    for bad in (181, -1, 179, 163):
        with pytest.raises(DartsError):
            make_visit(s, bad)


def test_checkout_needs_darts_and_ends_leg():
    s = new_state(301, 2, 2)
    s.remaining = [40, 301]
    with pytest.raises(DartsError, match="How many darts"):
        make_visit(s, 40)
    s.remaining = [110, 301]
    with pytest.raises(DartsError, match="at least 2"):
        make_visit(s, 110, darts=1)
    v = play(s, 110, darts=2)
    assert v.checkout and s.legs_won == [1, 0] and s.leg_no == 2
    assert s.remaining == [301, 301] and s.turn == 1  # Anwurf wechselt


def test_game_winner_and_replay():
    s = new_state(301, 2, 2)
    visits = []

    def go(score, darts=None):
        visits.append(play(s, score, darts))

    # Leg 1 (Spieler 0 beginnt): 0 wirft 180 (Rest 121), 1 wirft 60, 0 checkt 121
    go(180); go(60); go(121, 3)
    assert s.legs_won == [1, 0] and s.turn == 1
    # Leg 2 (Spieler 1 beginnt): beide 140, 140 -> Rest 21, Spieler 1 checkt 21
    go(140); go(140); go(140); go(140); go(21, 2)
    assert s.legs_won == [1, 1] and s.turn == 0 and not s.finished
    # Leg 3 (Spieler 0 beginnt) entscheidet
    go(180); go(100); go(121, 3)
    assert s.finished and s.winner == 0 and s.legs_won == [2, 1]
    with pytest.raises(DartsError, match="already finished"):
        make_visit(s, 60)
    again = replay(301, 2, 2, visits)
    assert again.winner == 0 and again.legs_won == [2, 1]


def test_replay_rejects_wrong_order():
    with pytest.raises(DartsError):
        replay(501, 1, 2, [Visit(player=1, score=60, darts=3)])


def test_solo_practice():
    s = new_state(301, 1, 1)
    play(s, 180); play(s, 81)
    v = play(s, 40, darts=1)
    assert v.checkout and s.finished and s.winner == 0


# ---------------------------------------------------------------- Doppel


def test_doubles_order_and_team_score():
    s = new_state(301, 2, 4, team_size=2)  # Positionen: 0=T1P1, 1=T2P1, 2=T1P2, 3=T2P2
    assert s.n_sides == 2 and [s.side(p) for p in range(4)] == [0, 1, 0, 1]
    play(s, 100); play(s, 60); play(s, 100)  # Team 1: 101 Rest, Team 2: 241
    assert s.remaining == [101, 241] and s.turn == 3
    play(s, 140)  # Team 2: 101
    v = play(s, 101, darts=3)  # Position 0 (Team 1) checkt
    assert v.checkout and s.legs_won == [1, 0] and s.leg_no == 2
    assert s.turn == 1  # Leg 2: Anwurf wandert eine Position weiter (Team 2, Spieler 1)
    with pytest.raises(DartsError):
        new_state(501, 1, 3, team_size=2)


def test_doubles_bust_uses_team_rest():
    s = new_state(301, 1, 4, team_size=2)
    s.remaining = [40, 301]
    v = play(s, 60)  # Team 1 hat nur noch 40
    assert v.bust and s.remaining == [40, 301]


def _random_score(rng, rest):
    if rng.random() < 0.15 and rest <= 170:
        return rest  # Checkout-Versuch
    return rng.choice([0, 26, 41, 45, 60, 81, 85, 100, 121, 140, 180, rng.randint(0, 60)])


@pytest.mark.parametrize("seed", range(40))
def test_random_games_invariants(seed):
    import random
    rng = random.Random(seed)
    team_size = 2 if seed % 3 == 0 else 1
    n = 4 if team_size == 2 else rng.randint(1, 4)
    start, legs = rng.choice([301, 501]), rng.randint(1, 3)
    s = new_state(start, legs, n, team_size)
    visits, leg_points = [], {}
    for _ in range(3000):
        if s.finished:
            break
        side, rest = s.side(s.turn), s.remaining[s.side(s.turn)]
        score = _random_score(rng, rest)
        darts = 3 if score == rest else None
        try:
            v = make_visit(s, score, darts)
        except DartsError:
            continue  # z. B. unmöglicher Checkout - wie eine abgelehnte Eingabe
        key = (s.leg_no, side)
        advance(s, v)
        visits.append(v)
        leg_points[key] = leg_points.get(key, 0) + v.score
        if v.checkout:
            assert leg_points[key] == start  # ein gewonnenes Leg ergibt genau den Startwert
        else:
            assert all(r >= 2 or r == start for r in s.remaining) and all(r >= 0 for r in s.remaining)
    assert s.finished, "game did not finish"
    again = replay(start, legs, n, visits, team_size)
    assert (again.winner, again.legs_won, again.leg_no) == (s.winner, s.legs_won, s.leg_no)
    assert max(s.legs_won) == legs
