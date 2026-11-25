"""Cricket, Around the Clock, Shanghai, Killer: Regeln + Zufalls-Simulation."""

import random

import pytest

from app.darts.engine import DartsError
from app.darts.modes import CRICKET_TARGETS, apply_visit, dart_label, new_mode_state, parse_dart, replay_mode


def test_parse_and_label():
    assert parse_dart("t20") == (3, 20) and parse_dart("SB") == (1, 25) and parse_dart("DB") == (2, 25)
    assert parse_dart("M") == (0, 0) and dart_label("DB") == "Bull" and dart_label("SB") == "25"
    assert dart_label("T19") == "T19" and dart_label("S5") == "5" and dart_label("M") == "–"
    for bad in ("T21", "X5", "D0", "TB", ""):
        with pytest.raises(DartsError):
            parse_dart(bad)


# ---------------------------------------------------------------- Cricket


def test_cricket_close_and_score():
    s = new_mode_state("cricket", 2)
    apply_visit(s, ["T20", "S20", "S20"])  # 3 zu, dann 2 Extra = 40 Punkte (Gegner offen)
    assert s.marks[0][20] == 3 and s.points[0] == 40 and s.turn == 1
    apply_visit(s, ["T20", "T20", "M"])  # schließt 20, Extra 3x20 = 60? Nein: Gegner hat 20 zu -> 0 Punkte
    assert s.marks[1][20] == 3 and s.points[1] == 0
    apply_visit(s, ["T20", "M", "M"])  # beide zu -> keine Punkte mehr
    assert s.points[0] == 40


def test_cricket_win_needs_points():
    s = new_mode_state("cricket", 2)
    s.marks[0] = {t: 3 for t in CRICKET_TARGETS}
    s.marks[0][15] = 2
    s.points[1] = 50
    apply_visit(s, ["S15", "M", "M"])  # alles zu, aber weniger Punkte -> noch nicht gewonnen
    assert not s.finished
    s.turn = 0
    with pytest.raises(DartsError, match="leave out"):
        apply_visit(s, ["T20", "T20", "T20", ])  # 3x T20 = 180 > 50: gewinnt mit dem 1. Dart
    s2 = new_mode_state("cricket", 2)
    s2.marks[0] = {t: 3 for t in CRICKET_TARGETS}
    s2.marks[1][20] = 0
    s2.points[1] = 50
    r = apply_visit(s2, ["T20"])  # 60 Punkte -> 60 >= 50 und alles zu -> gewonnen mit 1 Dart
    assert r["won"] and s2.winner == 0


def test_bull_marks():
    s = new_mode_state("cricket", 2)
    apply_visit(s, ["DB", "SB", "M"])
    assert s.marks[0][25] == 3


# ---------------------------------------------------------------- Around the Clock


def test_atc():
    s = new_mode_state("atc", 1)
    apply_visit(s, ["S1", "T2", "M"])
    assert s.target[0] == 3
    s.target[0] = 20
    apply_visit(s, ["D20", "M", "M"])
    assert s.target[0] == 25 and not s.finished
    r = apply_visit(s, ["SB"])
    assert r["won"] and s.winner == 0
    with pytest.raises(DartsError, match="all 3 darts"):
        apply_visit(new_mode_state("atc", 1), ["S1"])


# ---------------------------------------------------------------- Shanghai


def test_shanghai_points_and_instant_win():
    s = new_mode_state("shanghai", 2)
    apply_visit(s, ["T1", "S1", "S5"])  # Runde 1: nur die 1 zählt -> 4
    apply_visit(s, ["D1", "M", "M"])
    assert s.points == [4, 2] and s.shanghai_round == 2
    r = apply_visit(s, ["S2", "D2", "T2"])  # Shanghai!
    assert r["won"] and s.winner == 0 and "Shanghai!" in s.log


def test_shanghai_tie_continues():
    s = new_mode_state("shanghai", 2, {"rounds": 7})
    for _ in range(7):
        apply_visit(s, ["M", "M", "M"]); apply_visit(s, ["M", "M", "M"])
    assert not s.finished and s.shanghai_round == 8  # 0:0 -> weiter mit der 8
    apply_visit(s, ["S8", "M", "M"]); apply_visit(s, ["M", "M", "M"])
    assert s.winner == 0


# ---------------------------------------------------------------- Killer


def test_killer_flow():
    s = new_mode_state("killer", 3, {"lives": 2, "numbers": [5, 10, 15]})
    apply_visit(s, ["D10", "S5", "M"])  # noch kein Killer: fremdes Doppel zählt nicht
    assert s.lives == [2, 2, 2] and not s.killer[0]
    s.turn = 0
    apply_visit(s, ["D5", "D10", "D10"])  # Killer, dann 2 Leben von Spieler 1 -> raus
    assert s.killer[0] and s.lives[1] == 0
    assert s.turn == 2  # Spieler 1 wird übersprungen
    apply_visit(s, ["D15", "D5", "D5"])  # Spieler 2 wird Killer und nimmt Spieler 0 beide Leben
    assert s.winner == 2


def test_killer_own_double_costs_life():
    s = new_mode_state("killer", 2, {"lives": 1, "numbers": [3, 4]})
    s.killer[0] = True
    r = apply_visit(s, ["D3"])  # eigenes Doppel als Killer -> selbst raus -> Gegner gewinnt
    assert r["won"] and s.winner == 1


def test_mode_validation():
    with pytest.raises(DartsError):
        new_mode_state("cricket", 1)
    with pytest.raises(DartsError):
        new_mode_state("killer", 2, {"numbers": [5, 5]})
    with pytest.raises(DartsError):
        new_mode_state("shanghai", 2, {"rounds": 8})
    with pytest.raises(DartsError):
        new_mode_state("golf", 2)


# ---------------------------------------------------------------- Simulation


def _rand_dart(rng, s):
    p = s.turn
    mult = rng.choice([1, 1, 1, 2, 3])
    if s.mode == "cricket":
        open_ = [t for t, m in s.marks[p].items() if m < 3] or list(s.marks[p])
        num = rng.choice(open_ + [rng.randint(1, 14)])
    elif s.mode == "atc":
        num = s.target[p] if rng.random() < 0.5 else rng.randint(1, 20)
    elif s.mode == "shanghai":
        num = s.shanghai_number() if rng.random() < 0.6 else rng.randint(1, 20)
    else:  # killer: oft Doppel auf eine Spielerzahl
        num, mult = rng.choice(s.numbers), (2 if rng.random() < 0.6 else 1)
    if rng.random() < 0.15:
        return "M"
    if num == 25:
        return "DB" if mult >= 2 else "SB"
    return "SDT"[mult - 1] + str(num)


@pytest.mark.parametrize("mode", ["cricket", "atc", "shanghai", "killer"])
@pytest.mark.parametrize("seed", range(25))
def test_random_mode_games(mode, seed):
    rng = random.Random(seed * 7 + len(mode))
    n = rng.randint(2, 4) if mode in ("cricket", "killer") else rng.randint(1, 4)
    opts = {"lives": rng.randint(1, 4), "numbers": rng.sample(range(1, 21), n)} if mode == "killer" else {}
    if mode == "shanghai":
        opts = {"rounds": rng.choice([7, 10, 20])}
    s = new_mode_state(mode, n, opts)
    visits = []
    for _ in range(5000):
        if s.finished:
            break
        before_points = list(s.points)
        before_target = list(s.target)
        throws = []
        for _ in range(3):
            throws.append(_rand_dart(rng, s))
        # Für kürzere Aufnahmen bei Spielende: probieren, sonst den Rest weglassen
        for k in (3, 2, 1):
            trial = replay_mode(mode, n, opts, visits)
            try:
                apply_visit(trial, throws[:k])
                throws = throws[:k]
                break
            except DartsError:
                continue
        else:
            pytest.fail(f"no valid visit for {throws}")
        apply_visit(s, throws)
        visits.append(throws)
        assert all(a >= b for a, b in zip(s.points, before_points)), "points went down"
        if mode == "cricket":
            assert all(0 <= m <= 3 for marks in s.marks for m in marks.values())
        if mode == "atc":
            assert all(a >= b for a, b in zip(s.target, before_target))
        if mode == "killer":
            assert all(x >= 0 for x in s.lives)
    assert s.finished, f"{mode} did not finish"
    if mode == "killer":
        assert [x > 0 for x in s.lives].count(True) == 1 and s.lives[s.winner] > 0
    if mode == "cricket":
        assert all(m == 3 for m in s.marks[s.winner].values())
    again = replay_mode(mode, n, opts, visits)
    assert again.winner == s.winner and again.points == s.points
