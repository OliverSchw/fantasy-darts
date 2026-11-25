"""Darts-Bots für X01: werfen Dart für Dart wie ein Mensch - zielen und je nach Stärke treffen oder streuen.

Zielwahl: passt der Checkout-Weg in die restlichen Darts, wird er geworfen (z. B. 121 -> T20, T15, D8). Sonst
bei großem Rest T20, bei kleinem eine Vorlage, die ein gutes Doppel übrig lässt (lieber D16/D20 als D1).

Streuung: Wer auf ein Feld zielt, trifft es mit einer Wahrscheinlichkeit je nach Stärke; daneben landet man
im Single derselben Zahl (Triple/Doppel verfehlt) oder in einem Nachbarfeld auf der Scheibe.
"""

import random
from dataclasses import dataclass

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
