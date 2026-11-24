"""Darts-Spiellogik: Bust, Checkout, Legs, Anwurf-Wechsel, Checkout-Vorschläge."""

import pytest

from app.darts.checkouts import checkout_route, is_finishable, min_darts
from app.darts.engine import DartsError, Visit, make_visit, new_state, play, replay


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
