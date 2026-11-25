"""Darts-Partyspiele mit Eingabe pro Dart: Cricket, Around the Clock, Shanghai, Killer.

Wie bei X01 werden nur die Aufnahmen gespeichert (je bis zu 3 Darts als Codes) und der Stand wird
nachgespielt. Dart-Codes: "S20", "D20", "T20" (Single/Double/Triple 1-20), "SB" (Outer Bull, 25),
"DB" (Bull, 50), "M" (daneben).

Ein Spiel hat genau ein Leg. Die Reihenfolge ist fest (Position 0, 1, 2 ...); bei Killer werden
ausgeschiedene Spieler übersprungen.
"""

from dataclasses import dataclass, field

from .engine import DartsError

MODES = {
    "cricket": {"name": "Cricket", "min": 2, "max": 4,
                "help": "Close 15–20 and Bull with 3 hits each (double = 2, treble = 3). Extra hits score points "
                        "while an opponent still has the number open. All closed and most points wins."},
    "atc": {"name": "Around the Clock", "min": 1, "max": 4,
            "help": "Hit 1, 2, 3 … 20 in order, then the Bull. Any single, double or treble of the target counts."},
    "shanghai": {"name": "Shanghai", "min": 1, "max": 4,
                 "help": "Round 1 only the 1 counts, round 2 only the 2 … Points = number × single/double/treble. "
                         "Single, double and treble of the target in one visit = Shanghai, instant win."},
    "killer": {"name": "Killer", "min": 2, "max": 4,
               "help": "Everyone gets a number and lives. Hit your own double to become a killer – then every double "
                       "of an opponent's number costs them a life (your own double costs you one). Last one standing wins."},
    # Training (allein oder bis zu 4): zählt nicht für Elo und Siege
    "bobs27": {"name": "Bob's 27", "min": 1, "max": 4, "training": True,
               "help": "Doubles practice. Start with 27 points. Round 1 throw at D1, round 2 at D2 … then the Bull. "
                       "Every hit adds the double's value, no hit in a round subtracts it. At 0 or below you're out. "
                       "Best score after 21 rounds wins."},
    "checkout121": {"name": "121 Checkout", "min": 1, "max": 4, "training": True,
                    "help": "Checkout practice. Check out 121 with 9 darts (double out). Made it: the next target is "
                            "one higher. Missed: one lower (never below 121). Most checkouts after the set number of "
                            "attempts wins, then the highest target reached."},
}
TRAINING = {k for k, m in MODES.items() if m.get("training")}
CRICKET_TARGETS = (20, 19, 18, 17, 16, 15, 25)
BOBS_TARGETS = tuple(range(1, 21)) + (25,)
CHECKOUT_START = 121


def parse_dart(code: str) -> tuple[int, int]:
    """'T20' -> (3, 20), 'SB' -> (1, 25), 'DB' -> (2, 25), 'M' -> (0, 0)."""
    code = code.strip().upper()
    if code == "M":
        return 0, 0
    if code in ("SB", "DB"):
        return (1 if code == "SB" else 2), 25
    if len(code) >= 2 and code[0] in "SDT" and code[1:].isdigit() and 1 <= int(code[1:]) <= 20:
        return "SDT".index(code[0]) + 1, int(code[1:])
    raise DartsError(f"“{code}” is not a valid dart.")


def dart_label(code: str) -> str:
    mult, num = parse_dart(code)
    if mult == 0:
        return "–"
    if num == 25:
        return "Bull" if mult == 2 else "25"
    return f"{'SDT'[mult - 1] if mult > 1 else ''}{num}"


@dataclass
class ModeState:
    mode: str
    n: int
    options: dict
    turn: int = 0
    winner: int | None = None
    visits: int = 0
    points: list[int] = field(default_factory=list)
    # Cricket: marks[position][target]; ATC: target[position]; Killer: lives/killer/numbers
    marks: list[dict] = field(default_factory=list)
    target: list[int] = field(default_factory=list)
    lives: list[int] = field(default_factory=list)
    killer: list[bool] = field(default_factory=list)
    numbers: list[int] = field(default_factory=list)
    log: list[str] = field(default_factory=list)  # kurze Meldungen der letzten Aufnahme (z. B. "Shanghai!")
    # Training: Bob's 27 (Runde pro Spieler) / 121 Checkout (Ziel, Rest, Aufnahmen im Versuch, Treffer)
    rounds_done: list[int] = field(default_factory=list)
    rest: list[int] = field(default_factory=list)
    attempt_visits: list[int] = field(default_factory=list)
    attempts: list[int] = field(default_factory=list)  # abgeschlossene Versuche
    successes: list[int] = field(default_factory=list)
    best: list[int] = field(default_factory=list)  # höchstes geschafftes Ziel

    @property
    def finished(self) -> bool:
        return self.winner is not None

    # ---- Shanghai
    @property
    def rounds(self) -> int:
        return int(self.options.get("rounds", 7))

    @property
    def shanghai_round(self) -> int:
        return self.visits // self.n + 1

    def shanghai_number(self, rnd: int | None = None) -> int:
        rnd = rnd or self.shanghai_round
        return (rnd - 1) % 20 + 1

    def alive(self, p: int) -> bool:
        if self.mode == "killer":
            return self.lives[p] > 0
        if self.mode == "bobs27":
            return self.points[p] > 0 and self.rounds_done[p] < len(BOBS_TARGETS)
        if self.mode == "checkout121":
            return self.attempts[p] < self.n_attempts
        return True

    # ---- Bob's 27 / 121 Checkout
    def bobs_target(self, p: int) -> int:
        return BOBS_TARGETS[min(self.rounds_done[p], len(BOBS_TARGETS) - 1)]

    @property
    def n_attempts(self) -> int:
        return int(self.options.get("attempts", 10))


def new_mode_state(mode: str, n: int, options: dict | None = None) -> ModeState:
    if mode not in MODES:
        raise DartsError("Unknown game mode.")
    lo, hi = MODES[mode]["min"], MODES[mode]["max"]
    if not lo <= n <= hi:
        raise DartsError(f"{MODES[mode]['name']} needs {lo}–{hi} players.")
    options = dict(options or {})
    s = ModeState(mode=mode, n=n, options=options, points=[0] * n)
    if mode == "cricket":
        s.marks = [{t: 0 for t in CRICKET_TARGETS} for _ in range(n)]
    elif mode == "atc":
        s.target = [1] * n
    elif mode == "shanghai":
        if s.rounds not in (7, 10, 20):
            raise DartsError("Shanghai is played over 7, 10 or 20 rounds.")
    elif mode == "killer":
        lives = int(options.get("lives", 3))
        if not 1 <= lives <= 9:
            raise DartsError("Killer needs 1–9 lives.")
        nums = options.get("numbers")
        if not nums or len(nums) != n or len(set(nums)) != n or not all(1 <= x <= 20 for x in nums):
            raise DartsError("Killer needs a different number (1–20) for every player.")
        s.numbers, s.lives, s.killer = list(nums), [lives] * n, [False] * n
    elif mode == "bobs27":
        s.points, s.rounds_done = [27] * n, [0] * n
    elif mode == "checkout121":
        if s.n_attempts not in (5, 10, 20):
            raise DartsError("121 Checkout is played with 5, 10 or 20 attempts.")
        s.target = [CHECKOUT_START] * n
        s.rest = [CHECKOUT_START] * n
        s.attempt_visits, s.attempts, s.successes, s.best = [0] * n, [0] * n, [0] * n, [0] * n
    return s


def _next_turn(s: ModeState) -> None:
    for step in range(1, s.n + 1):
        p = (s.turn + step) % s.n
        if s.alive(p):
            s.turn = p
            return


def _cricket_dart(s: ModeState, p: int, mult: int, num: int) -> int:
    if num not in CRICKET_TARGETS or mult == 0:
        return 0
    have = s.marks[p][num]
    to_close = max(0, 3 - have)
    s.marks[p][num] = min(3, have + mult)
    extra = mult - min(mult, to_close)
    if extra and any(s.marks[o][num] < 3 for o in range(s.n) if o != p):
        pts = extra * num
        s.points[p] += pts
        return pts
    return 0


def _cricket_won(s: ModeState, p: int) -> bool:
    return all(v >= 3 for v in s.marks[p].values()) and all(s.points[p] >= s.points[o] for o in range(s.n) if o != p)


def _finish_training(s: ModeState) -> None:
    """Wenn keiner mehr werfen kann: Sieger bestimmen (Gleichstand: wer zuerst dran war)."""
    if any(s.alive(p) for p in range(s.n)):
        return
    if s.mode == "bobs27":
        key = lambda p: s.points[p]  # noqa: E731
    else:
        key = lambda p: (s.successes[p], s.best[p])  # noqa: E731
    s.winner = max(range(s.n), key=key)


def _bobs27_visit(s: ModeState, p: int, darts: list[tuple[int, int]]) -> int:
    if len(darts) != 3:
        raise DartsError("Enter all 3 darts (use “Miss” for darts outside).")
    target = s.bobs_target(p)
    value = 2 * target
    hits = sum(1 for m, n_ in darts if m == 2 and n_ == target)
    change = hits * value if hits else -value
    s.points[p] += change
    s.rounds_done[p] += 1
    if s.points[p] <= 0:
        s.log.append("out")
    return change


def _checkout_visit(s: ModeState, p: int, darts: list[tuple[int, int]]) -> int:
    """Eine Aufnahme im 121-Versuch: Double-out, Bust setzt auf den Rest vor der Aufnahme zurück."""
    rest = s.rest[p]
    scored, done = 0, None
    for i, (m, n_) in enumerate(darts):
        if done:
            raise DartsError("The visit was already over – leave out the remaining darts.")
        left = rest - scored - m * n_
        if left == 0 and m == 2:
            done = "checkout"
        elif left < 2:
            done = "bust"
        scored += m * n_
    if not done and len(darts) < 3:
        raise DartsError("Enter all 3 darts (use “Miss” for darts outside).")
    s.attempt_visits[p] += 1
    if done == "checkout":
        s.successes[p] += 1
        s.best[p] = max(s.best[p], s.target[p])
        s.log.append("Checkout!")
        s.target[p] += 1
    elif done == "bust":
        s.log.append("bust")
        scored = 0
    else:
        s.rest[p] = rest - scored
    if done == "checkout" or s.attempt_visits[p] >= 3:  # Versuch vorbei
        if done != "checkout":
            s.target[p] = max(CHECKOUT_START, s.target[p] - 1)
        s.attempts[p] += 1
        s.attempt_visits[p] = 0
        s.rest[p] = s.target[p]
    return scored if done != "bust" else 0


def apply_visit(s: ModeState, throws: list[str]) -> dict:
    """Wendet eine Aufnahme (1-3 Dart-Codes) für den Spieler an, der dran ist.
    Weniger als 3 Darts nur, wenn das Spiel damit endet. Gibt {"points": ..., "won": bool} zurück."""
    if s.finished:
        raise DartsError("This game is already finished.")
    if not 1 <= len(throws) <= 3:
        raise DartsError("Enter 1 to 3 darts.")
    darts = [parse_dart(t) for t in throws]
    p, gained = s.turn, 0
    s.log = []
    if s.mode in TRAINING:
        if s.mode == "bobs27":
            gained = _bobs27_visit(s, p, darts)
        else:
            attempt_before = s.attempts[p]
            gained = _checkout_visit(s, p, darts)
        s.visits += 1
        won = "Checkout!" in s.log
        _finish_training(s)
        # Bob's 27: nach jeder Runde der Nächste. 121: ein Versuch (bis zu 3 Aufnahmen) am Stück.
        if not s.finished and (s.mode == "bobs27" or s.attempts[p] != attempt_before or not s.alive(p)):
            _next_turn(s)
        return {"points": gained, "won": won}
    for i, (mult, num) in enumerate(darts):
        if s.finished:
            raise DartsError("The game was already decided – leave out the remaining darts.")
        if s.mode == "cricket":
            gained += _cricket_dart(s, p, mult, num)
            if _cricket_won(s, p):
                s.winner = p
        elif s.mode == "atc":
            goal = s.target[p]
            if mult and num == goal:
                s.target[p] = 25 if goal == 20 else (26 if goal == 25 else goal + 1)
                if s.target[p] == 26:
                    s.winner = p
        elif s.mode == "shanghai":
            if mult and num == s.shanghai_number():
                s.points[p] += mult * num
                gained += mult * num
        elif s.mode == "killer":
            if mult != 2 or num == 25:
                continue
            owner = next((o for o in range(s.n) if s.numbers[o] == num and s.lives[o] > 0), None)
            if owner is None:
                continue
            if not s.killer[p]:
                if owner == p:
                    s.killer[p] = True
                    s.log.append("Killer!")
            else:
                s.lives[owner] -= 1
                if s.lives[owner] == 0:
                    s.log.append("out")
                alive = [o for o in range(s.n) if s.lives[o] > 0]
                if len(alive) == 1:
                    s.winner = alive[0]
                elif s.lives[p] == 0:  # eigenes Leben verloren -> Aufnahme vorbei
                    if i < len(darts) - 1:
                        raise DartsError("You knocked yourself out – leave out the remaining darts.")
                    break
    if s.mode == "shanghai" and not s.finished:
        hit = {m for m, n_ in darts if n_ == s.shanghai_number() and m}
        if hit == {1, 2, 3}:
            s.winner = p
            s.log.append("Shanghai!")
    if not s.finished and len(darts) < 3 and not (s.mode == "killer" and s.lives[p] == 0):
        raise DartsError("Enter all 3 darts (use “Miss” for darts outside).")
    s.visits += 1
    if not s.finished:
        if s.mode == "shanghai" and s.visits % s.n == 0 and s.shanghai_round > s.rounds:
            best = max(s.points)
            leaders = [o for o in range(s.n) if s.points[o] == best]
            if len(leaders) == 1:
                s.winner = leaders[0]
        if not s.finished:
            _next_turn(s)
    return {"points": gained, "won": s.finished}


def replay_mode(mode: str, n: int, options: dict, visits: list[list[str]]) -> ModeState:
    s = new_mode_state(mode, n, options)
    for throws in visits:
        apply_visit(s, throws)
    return s
