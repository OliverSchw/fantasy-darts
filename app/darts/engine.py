"""X01-Spiellogik (301/501/701, Double-Out) als reine Funktionen.

Gespeichert werden nur die Aufnahmen (Visits). Der Spielstand - Rest, Legs, wer dran ist, Sieger -
wird daraus jedes Mal nachgespielt. So kann "Rückgängig" einfach die letzte Aufnahme löschen.
"""

from dataclasses import dataclass, field

from .checkouts import is_finishable, min_darts

# Mit drei Darts nicht erreichbare Punktzahlen
IMPOSSIBLE_SCORES = frozenset({163, 166, 169, 172, 173, 175, 176, 178, 179})
START_SCORES = (301, 501, 701)


class DartsError(ValueError):
    """Ungültige Eingabe - die Meldung ist für den Spieler gedacht."""


@dataclass(frozen=True)
class Visit:
    player: int  # Index in der Spielerreihenfolge
    score: int  # gezählte Punkte (0 bei Bust)
    darts: int  # geworfene Darts (3, beim Checkout 1-3)
    bust: bool = False
    checkout: bool = False


@dataclass
class GameState:
    start: int
    legs_to_win: int
    n_players: int
    leg_no: int = 1
    remaining: list[int] = field(default_factory=list)
    legs_won: list[int] = field(default_factory=list)
    turn: int = 0
    winner: int | None = None
    leg_visits: list[Visit] = field(default_factory=list)  # Aufnahmen im laufenden Leg

    @property
    def finished(self) -> bool:
        return self.winner is not None

    @property
    def leg_starter(self) -> int:
        """Der Anwurf wechselt jedes Leg."""
        return (self.leg_no - 1) % self.n_players


def new_state(start: int, legs_to_win: int, n_players: int) -> GameState:
    if start not in START_SCORES:
        raise DartsError("Start score must be 301, 501 or 701.")
    if not 1 <= legs_to_win <= 11:
        raise DartsError("Legs to win must be between 1 and 11.")
    if not 1 <= n_players <= 4:
        raise DartsError("A game needs 1 to 4 players.")
    return GameState(start=start, legs_to_win=legs_to_win, n_players=n_players,
                     remaining=[start] * n_players, legs_won=[0] * n_players)


def advance(state: GameState, visit: Visit) -> None:
    """Wendet eine (gültige) Aufnahme auf den Stand an."""
    state.remaining[visit.player] -= visit.score
    state.leg_visits.append(visit)
    if visit.checkout:
        state.legs_won[visit.player] += 1
        if state.legs_won[visit.player] >= state.legs_to_win:
            state.winner = visit.player
            return
        state.leg_no += 1
        state.remaining = [state.start] * state.n_players
        state.leg_visits = []
        state.turn = state.leg_starter
    else:
        state.turn = (state.turn + 1) % state.n_players


def make_visit(state: GameState, score: int, darts: int | None = None) -> Visit:
    """Prüft eine Eingabe für den Spieler, der dran ist, und gibt die zu speichernde Aufnahme zurück.

    - Mehr als der Rest, Rest 1 oder ein nicht ausmachbarer Rest -> Bust (zählt 0, 3 Darts).
    - Genau der Rest -> Checkout; dafür muss angegeben werden, mit wie vielen Darts (1-3).
    """
    if state.finished:
        raise DartsError("This game is already finished.")
    if not isinstance(score, int) or not 0 <= score <= 180 or score in IMPOSSIBLE_SCORES:
        raise DartsError(f"{score} is not possible with three darts.")
    player = state.turn
    rest = state.remaining[player]
    if score == rest and is_finishable(rest):
        needed = min_darts(rest)
        if darts is None:
            raise DartsError("How many darts did the checkout take?")
        if not needed <= darts <= 3:
            raise DartsError(f"{rest} needs at least {needed} dart{'s' if needed > 1 else ''}.")
        return Visit(player=player, score=score, darts=darts, checkout=True)
    if score >= rest - 1:  # überworfen, auf 1 gelandet oder Rest nicht per Doppel ausmachbar
        return Visit(player=player, score=0, darts=3, bust=True)
    return Visit(player=player, score=score, darts=3)


def replay(start: int, legs_to_win: int, n_players: int, visits: list[Visit]) -> GameState:
    """Spielt gespeicherte Aufnahmen nach. Wirft DartsError, wenn sie nicht zusammenpassen."""
    state = new_state(start, legs_to_win, n_players)
    for v in visits:
        if state.finished:
            raise DartsError("Visit after the end of the game.")
        if v.player != state.turn:
            raise DartsError("Visits are out of order.")
        advance(state, v)
    return state


def play(state: GameState, score: int, darts: int | None = None) -> Visit:
    """make_visit + anwenden (für Tests und Vorschau)."""
    visit = make_visit(state, score, darts)
    advance(state, visit)
    return visit
