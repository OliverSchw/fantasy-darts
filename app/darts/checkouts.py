"""Checkout-Wege (Double-Out) für 2..170 - einmal beim Import berechnet.

Bevorzugt: wenige Darts, beliebte Doppel (D20, D16, D8 ...) und übliche Vorlagen (T20, T19 ...).
"""

from functools import lru_cache

# Alle möglichen Einzelwürfe: (Name, Punkte)
SINGLES = [(f"{n}", n) for n in range(20, 0, -1)] + [("25", 25)]
DOUBLES = [(f"D{n}", 2 * n) for n in range(20, 0, -1)] + [("Bull", 50)]
TREBLES = [(f"T{n}", 3 * n) for n in range(20, 0, -1)]
ALL_DARTS = TREBLES + SINGLES + DOUBLES

# Reihenfolge der Vorlieben (kleiner = lieber)
_DOUBLE_PREF = ["D20", "D16", "D8", "D18", "D12", "D10", "D4", "D2", "D14", "D6", "D19", "D17", "D15",
                "D13", "D11", "D9", "D7", "D5", "D3", "Bull", "D1"]
_TREBLE_PREF = ["T20", "T19", "T18", "T17", "T16", "T15", "T14", "T13", "T12", "T11", "T10"]
_SINGLE_RANK, _OUTER_BULL_RANK, _BULL_SETUP_RANK, _OTHER_RANK = 10, 12, 14, 20


def _rank(name: str, pref: list[str]) -> int:
    return pref.index(name) if name in pref else len(pref) + 1


def _setup_rank(name: str) -> int:
    """Vorlage: kräftige Triple vorne, alle Einzelfelder gleich gut, Doppel/kleine Triple zuletzt."""
    if name in _TREBLE_PREF:
        return _TREBLE_PREF.index(name)
    if name.isdigit() and name != "25":
        return _SINGLE_RANK
    return {"25": _OUTER_BULL_RANK, "Bull": _BULL_SETUP_RANK}.get(name, _OTHER_RANK)


def _cost(route: tuple[str, ...]) -> tuple:
    """Weniger Darts zuerst; danach beliebtes Doppel (doppelt gewichtet) plus einfache Vorlagen."""
    *setup, last = route
    return (len(route), 2 * _rank(last, _DOUBLE_PREF) + sum(_setup_rank(d) for d in setup))


@lru_cache(maxsize=1)
def _table() -> dict[int, tuple[str, ...]]:
    best: dict[int, tuple[str, ...]] = {}

    def offer(total: int, route: tuple[str, ...]):
        if 2 <= total <= 170 and (total not in best or _cost(route) < _cost(best[total])):
            best[total] = route

    for dn, dv in DOUBLES:
        offer(dv, (dn,))
        for an, av in ALL_DARTS:
            offer(av + dv, (an, dn))
            for bn, bv in ALL_DARTS:
                # Reihenfolge der Vorlagen egal -> größere Vorlage zuerst werfen
                if av >= bv:
                    offer(av + bv + dv, (an, bn, dn))
    return best


def checkout_route(remaining: int) -> tuple[str, ...] | None:
    """Vorschlag für einen Rest, z. B. 170 -> ("T20", "T20", "Bull"); None, wenn nicht in 3 Darts möglich."""
    return _table().get(remaining)


def min_darts(remaining: int) -> int | None:
    """Wie viele Darts man mindestens braucht, um den Rest auszumachen (1-3), sonst None."""
    route = checkout_route(remaining)
    return len(route) if route else None


def is_finishable(remaining: int) -> bool:
    return checkout_route(remaining) is not None
