"""X01 Dart für Dart: aus einzelnen Darts ("T20", "D16", "M" ...) die Aufnahme bestimmen und Doppel zählen.

Wer Dart für Dart eingibt, bekommt zusätzlich die Doppelquote: jeder Dart, der auf einem Rest geworfen wird,
der mit einem einzigen Doppel ausgeht (2-40 gerade, oder 50 wenn der Dart Richtung Bull geht), ist ein Versuch;
trifft er genau dieses Doppel, ist es ein Treffer.
"""

from .engine import DartsError, GameState, Visit
from .modes import parse_dart


def is_double_out(rest: int) -> bool:
    return rest == 50 or (2 <= rest <= 40 and rest % 2 == 0)


def x01_visit(state: GameState, throws: list[str]) -> Visit:
    """Aufnahme aus 1-3 Darts für den Spieler, der dran ist (Double-out).
    Weniger als 3 Darts nur, wenn die Aufnahme damit vorbei ist (Checkout oder Bust)."""
    if state.finished:
        raise DartsError("This game is already finished.")
    if not 1 <= len(throws) <= 3:
        raise DartsError("Enter 1 to 3 darts.")
    darts = [parse_dart(t) for t in throws]
    player = state.turn
    rest = state.remaining[state.side(player)]
    total = 0
    for i, (mult, num) in enumerate(darts):
        total += mult * num
        left = rest - total
        over = left == 0 or left < 2
        if over and i < len(darts) - 1:
            raise DartsError("The visit was already over – leave out the remaining darts.")
        if left == 0 and mult == 2:
            return Visit(player=player, score=total, darts=i + 1, checkout=True)
        if over:  # überworfen, auf 1 gelandet oder nicht mit einem Doppel ausgemacht
            return Visit(player=player, score=0, darts=3, bust=True)
    if len(darts) < 3:
        raise DartsError("Enter all 3 darts (use “Miss” for darts outside).")
    return Visit(player=player, score=total, darts=3)


def double_attempts(remaining_before: int, throws: list[str] | None) -> tuple[int, int]:
    """(Darts auf ein Doppel, davon getroffen) in einer Aufnahme."""
    if not throws:
        return 0, 0
    rest, tries, hits = remaining_before, 0, 0
    for code in throws:
        mult, num = parse_dart(code)
        # Bei 50 Rest zählt nur ein Dart Richtung Bull (25/Bull) - mit z. B. S10 stellt man sich 40 übrig
        if is_double_out(rest) and (rest != 50 or num == 25):
            tries += 1
            if mult == 2 and 2 * num == rest:
                hits += 1
                break
        rest -= mult * num
        if rest < 2:
            break
    return tries, hits
