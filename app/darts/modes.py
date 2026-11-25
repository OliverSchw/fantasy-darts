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
}
CRICKET_TARGETS = (20, 19, 18, 17, 16, 15, 25)


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
        return self.mode != "killer" or self.lives[p] > 0


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
