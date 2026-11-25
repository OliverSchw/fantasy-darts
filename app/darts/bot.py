"""Darts-Bots für X01: werfen Dart für Dart wie ein Mensch - zielen und je nach Stärke treffen oder streuen.

Zielwahl: passt der Checkout-Weg in die restlichen Darts, wird er geworfen (z. B. 121 -> T20, T15, D8). Sonst
bei großem Rest T20, bei kleinem eine Vorlage, die ein gutes Doppel übrig lässt (lieber D16/D20 als D1).

Streuung: Wer auf ein Feld zielt, trifft es mit einer Wahrscheinlichkeit je nach Stärke; daneben landet man
im Single derselben Zahl (Triple/Doppel verfehlt) oder in einem Nachbarfeld auf der Scheibe.
"""

import random
from dataclasses import dataclass
from functools import lru_cache

from .checkouts import checkout_route, min_darts
from .engine import GameState
from .modes import parse_dart
from .throws import is_double_out

# Zahlen im Uhrzeigersinn (für die Nachbarfelder)
BOARD = (20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5)


@dataclass(frozen=True)
class Level:
    key: str
    name: str
    treble: float  # Triple getroffen, wenn darauf gezielt
    double: float  # Doppel getroffen
    single: float  # Single getroffen (bei Triple-Ziel: landet im Single derselben Zahl)
    bull: float  # Bull (50) getroffen
    average: int  # ungefährer 3-Dart-Average (nur zur Anzeige)


LEVELS = {
    "easy": Level("easy", "Easy Bot", 0.07, 0.11, 0.60, 0.05, 35),
    "medium": Level("medium", "Medium Bot", 0.17, 0.22, 0.72, 0.10, 55),
    "hard": Level("hard", "Hard Bot", 0.29, 0.34, 0.82, 0.18, 75),
    "pro": Level("pro", "Pro Bot", 0.43, 0.46, 0.90, 0.28, 95),
}


def _neighbour(num: int, rng: random.Random) -> int:
    i = BOARD.index(num)
    return BOARD[(i + rng.choice((-1, 1))) % 20]


def throw_dart(aim: str, level: Level, rng: random.Random) -> str:
    """Wo landet ein Dart, der auf `aim` ("T20", "D16", "S5", "DB", "SB") geworfen wird?"""
    mult, num = parse_dart(aim)
    r = rng.random()
    if num == 25:  # Bull / Outer Bull
        p = level.bull if mult == 2 else min(0.8, 2.2 * level.bull)
        if r < p:
            return aim
        if rng.random() < 0.4:
            return "SB" if mult == 2 else "DB"
        return f"S{rng.choice(BOARD)}"
    if mult == 3:
        if r < level.treble:
            return aim
        if r < level.treble + (1 - level.treble) * level.single:
            return f"S{num}"
        nb = _neighbour(num, rng)
        return f"T{nb}" if rng.random() < 0.12 else f"S{nb}"
    if mult == 2:
        if r < level.double:
            return aim
        r2 = rng.random()
        if r2 < 0.45:
            return f"S{num}"  # zu weit innen
        if r2 < 0.85:
            return "M"  # außen vorbei
        nb = _neighbour(num, rng)
        return f"D{nb}" if rng.random() < 0.3 else f"S{nb}"
    # Single
    if r < min(0.95, level.single + 0.2):
        return aim
    r2 = rng.random()
    if r2 < 0.15:
        return f"T{num}"
    if r2 < 0.25:
        return f"D{num}"
    return f"S{_neighbour(num, rng)}"


def _code(name: str) -> str:
    """Namen aus der Checkout-Tabelle ("T20", "19", "25", "D16", "Bull") -> Dart-Code."""
    if name == "Bull":
        return "DB"
    if name == "25":
        return "SB"
    return name if name[0] in "TD" else f"S{name}"


_LEAVE_BONUS = {32: 6, 40: 5, 16: 4, 24: 3, 36: 3, 20: 3, 8: 2, 12: 2, 4: 1}
_SETUPS = [f"S{n}" for n in range(1, 21)] + [f"T{n}" for n in range(1, 21)] + ["SB"]


def choose_aim(rest: int, darts_left: int) -> str:
    """Worauf der nächste Dart geht (Double-out)."""
    route = checkout_route(rest)
    if route and len(route) <= darts_left:
        return _code(route[0])
    if rest > 100:
        return "T20" if rest - 60 >= 2 else "T19"

    def quality(aim: str) -> tuple:
        m, n = parse_dart(aim)
        leave = rest - m * n
        if leave < 2:
            return (-1, 0)
        if is_double_out(leave) and leave != 50:
            return (3, _LEAVE_BONUS.get(leave, 0), -m)  # lieber per Single als per Triple vorlegen
        md = min_darts(leave)
        return (2 if md == 2 else 1 if md else 0, -leave, -m)
    return max(_SETUPS, key=quality)


def bot_visit(state: GameState, level: Level, rng: random.Random) -> list[str]:
    """Darts einer Aufnahme für den Bot, der dran ist - endet nach Checkout oder Bust vorzeitig."""
    rest = state.remaining[state.side(state.turn)]
    throws: list[str] = []
    left = rest
    for i in range(3):
        dart = throw_dart(choose_aim(left, 3 - i), level, rng)
        throws.append(dart)
        m, n = parse_dart(dart)
        left -= m * n
        if left == 0 and m == 2:
            break  # Checkout
        if left < 2:
            break  # Bust
    return throws


# ---------------------------------------------------------------- Eigene Bots (Average + Doppelquote frei wählbar)
#
# Ein eigener Bot hat eine Wurfstärke x (0 = Anfänger, 1 = Pro, 1.25 = Weltklasse) für Triple/Single/Bull
# und eine eigene Doppel-Trefferquote. x wird per Simulation so gesucht, dass der gewünschte Average
# herauskommt (die Doppelquote fließt mit ein, weil Fehlwürfe aufs Doppel Darts kosten).

# (x, Triple, Single, Bull) - die Stufen oben liegen bei x = 0.25 / 0.5 / 0.75 / 1.0
_KNOTS = ((0.0, 0.02, 0.40, 0.02), (0.25, 0.07, 0.60, 0.05), (0.5, 0.17, 0.72, 0.10),
          (0.75, 0.29, 0.82, 0.18), (1.0, 0.43, 0.90, 0.28), (1.25, 0.58, 0.95, 0.38))
AVG_RANGE = (20, 110)
DOUBLE_RANGE = (3, 65)


def skill_level(x: float, double_pct: float, name: str = "Custom Bot", average: int = 0) -> Level:
    x = max(_KNOTS[0][0], min(_KNOTS[-1][0], x))
    for (x0, *a), (x1, *b) in zip(_KNOTS, _KNOTS[1:]):
        if x <= x1:
            f = (x - x0) / (x1 - x0)
            t, s, bull = (u + f * (v - u) for u, v in zip(a, b))
            break
    return Level("custom", name, t, double_pct / 100, s, bull, average)


def simulate_average(level: Level, legs: int = 150, seed: int = 7) -> float:
    rng = random.Random(seed)
    from .engine import advance, new_state
    from .throws import x01_visit
    darts = points = 0
    for _ in range(legs):
        st = new_state(501, 1, 1)
        while not st.finished:
            v = x01_visit(st, bot_visit(st, level, rng))
            darts += v.darts
            points += v.score
            advance(st, v)
    return 3 * points / darts


@lru_cache(maxsize=256)
def calibrate(average: int, double_pct: int) -> float:
    """Wurfstärke x, mit der ein Bot mit dieser Doppelquote ungefähr diesen Average wirft."""
    lo, hi = _KNOTS[0][0], _KNOTS[-1][0]
    for _ in range(11):
        mid = (lo + hi) / 2
        if simulate_average(skill_level(mid, double_pct), legs=250) < average:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 4)


def check_custom(average, double_pct) -> tuple[int, int]:
    """Eingaben prüfen und runden (Average 20-110, Doppelquote 3-65 %)."""
    try:
        a, d = round(float(average)), round(float(double_pct))
    except (TypeError, ValueError):
        raise ValueError("Enter an average and a double rate for the bot.") from None
    if not AVG_RANGE[0] <= a <= AVG_RANGE[1]:
        raise ValueError(f"The bot's average must be between {AVG_RANGE[0]} and {AVG_RANGE[1]}.")
    if not DOUBLE_RANGE[0] <= d <= DOUBLE_RANGE[1]:
        raise ValueError(f"The bot's double rate must be between {DOUBLE_RANGE[0]} and {DOUBLE_RANGE[1]} %.")
    return a, d


def estimated_double_pct(average: float) -> int:
    """Doppelquote passend zu einem Average (wenn jemand nie Dart für Dart eingegeben hat)."""
    pts = ((20, 6), (37, 11), (57, 23), (76, 32), (95, 47), (110, 55))
    for (a0, d0), (a1, d1) in zip(pts, pts[1:]):
        if average <= a1:
            return round(d0 + max(0, average - a0) / (a1 - a0) * (d1 - d0))
    return pts[-1][1]


PRESET_X = {"easy": 0.25, "medium": 0.5, "hard": 0.75, "pro": 1.0}  # Lage der festen Stufen auf der Skala
FORM_SPREAD = 0.07  # Tagesform: so stark schwankt die Wurfstärke von Spiel zu Spiel (etwa ±5 Average)


def level_for(competitor, game_id: int | None = None) -> Level | None:
    """Wurf-Stärke eines Bot-Teilnehmers (feste Stufe oder eigener Bot mit gespeicherter Einstellung).
    Mit game_id hat der Bot eine Tagesform: in jedem Spiel etwas besser oder schlechter (fest pro Spiel)."""
    key = competitor.bot_level
    if not key:
        return None
    if key in LEVELS:
        base = LEVELS[key]
        x, dbl, avg = PRESET_X[key], 100 * base.double, base.average
    else:
        cfg = competitor.bot_config or {}
        x, dbl, avg = float(cfg.get("x", 0.5)), float(cfg.get("double", 20)), int(cfg.get("average", 0))
    if game_id is not None:
        rng = random.Random(f"{game_id}-{competitor.id}")
        x += rng.gauss(0, FORM_SPREAD)
        dbl = min(70.0, max(2.0, dbl * rng.gauss(1, 0.15)))
    return skill_level(x, dbl, competitor.name, avg)
