"""Aufbereitung des Turnierbaums für die Anzeige (reine Funktionen, keine DB).

- Baum in Abschnitte teilen (Achtel + Finals), damit er aufs Handy passt
- für noch offene Plätze die möglichen Gegner ("A / B") ermitteln
- Status pro Spieler: nächster Gegner, ausgeschieden in Runde X, Weltmeister
"""

from dataclasses import dataclass, field

from .models import Match, Player
from .rules import Rules


@dataclass
class Side:
    pid: int | None
    candidates: tuple[int, ...] = ()  # wenn pid noch offen: die beiden Spieler des Vor-Matches
    sets: int = 0
    won: bool = False
    lost: bool = False


@dataclass
class MatchView:
    match: Match
    sides: tuple[Side, Side]


@dataclass
class Column:
    round_no: int | None  # None = Champion-Spalte
    title: str
    groups: list[list[MatchView]]  # Paare von Matches (für die Verbindungslinien)
    first: bool = False
    last: bool = False


@dataclass
class Section:
    key: str
    label: str
    columns: list[Column] = field(default_factory=list)
    champion: Side | None = None


@dataclass
class PlayerStatus:
    state: str  # "alive" | "out" | "champion" | "none"
    round_no: int | None = None
    match: Match | None = None
    opponent: Side | None = None


class Bracket:
    def __init__(self, rules: Rules, matches: list[Match], players: dict[int, Player]):
        self.rules = rules
        self.players = players
        self.n = rules.tournament.num_rounds
        self.by_pos = {(m.round, m.slot): m for m in matches}
        self._latest: dict[int, Match] = {}
        for m in sorted(matches, key=lambda m: m.round):
            for pid in (m.p1_id, m.p2_id):
                if pid is not None:
                    self._latest[pid] = m

    # ------------------------------------------------------------ Bausteine

    def side(self, m: Match, idx: int) -> Side:
        pid = m.p1_id if idx == 0 else m.p2_id
        if pid is None:
            feeder = self.by_pos.get((m.round - 1, 2 * m.slot + idx))
            cands = tuple(p for p in (feeder.p1_id, feeder.p2_id) if p is not None) if feeder else ()
            return Side(None, cands if len(cands) == 2 else ())
        sets = m.sets_p1 if idx == 0 else m.sets_p2
        return Side(pid, (), sets, m.winner_id == pid, m.is_played and m.winner_id != pid)

    def view(self, m: Match) -> MatchView:
        return MatchView(m, (self.side(m, 0), self.side(m, 1)))

    def _column(self, rnd: int, slots: range, pair: bool) -> Column:
        views = [self.view(self.by_pos[(rnd, s)]) for s in slots if (rnd, s) in self.by_pos]
        groups = [views[i:i + 2] for i in range(0, len(views), 2)] if pair else [[v] for v in views]
        return Column(rnd, self.rules.tournament.round_names[rnd - 1], groups)

    # ------------------------------------------------------------ Abschnitte

    @property
    def split_round(self) -> int:
        """Bis zu dieser Runde wird in Abschnitte geteilt (Rest = Finals). 7 Runden -> 4."""
        return max(1, self.n - 3)

    def sections(self) -> list[Section]:
        split = self.split_round
        n_sections = self.rules.matches_in_round(split) if self.n > 3 else 1
        sections = []
        if self.n > 3:
            for s in range(n_sections):
                sec = Section(key=str(s + 1), label=self._section_label(s, split))
                for rnd in range(1, split + 1):
                    per = 2 ** (split - rnd)
                    sec.columns.append(self._column(rnd, range(s * per, (s + 1) * per), pair=rnd < split))
                sections.append(sec)
            first_final = split + 1
        else:
            first_final = 1
        finals = Section(key="finals", label="Finals")
        for rnd in range(first_final, self.n + 1):
            finals.columns.append(self._column(rnd, range(self.rules.matches_in_round(rnd)), pair=rnd < self.n))
        final = self.by_pos.get((self.n, 0))
        winner = final.winner_id if final else None
        finals.champion = Side(winner, won=winner is not None)
        finals.columns.append(Column(None, "Champion", []))
        sections.append(finals)
        for sec in sections:
            sec.columns[0].first = True
            sec.columns[-1].last = True
        return sections

    def _section_label(self, s: int, split: int) -> str:
        per = 2 ** (split - 1)
        pids = []
        for slot in range(s * per, (s + 1) * per):
            m = self.by_pos.get((1, slot))
            if m:
                pids += [p for p in (m.p1_id, m.p2_id) if p is not None]
        seeded = [self.players[p] for p in pids if p in self.players and self.players[p].seed]
        if not seeded:
            return f"Section {s + 1}"
        return min(seeded, key=lambda p: p.seed).name.split(" ", 1)[-1]

    def section_of(self, pid: int) -> str | None:
        """In welchem Abschnitt steht der Spieler aktuell?"""
        m = self._latest.get(pid)
        if m is None:
            return None
        if m.round > self.split_round or self.n <= 3:
            return "finals"
        per = 2 ** (self.split_round - m.round)
        return str(m.slot // per + 1)

    # ------------------------------------------------------------ Spielerstatus

    def status(self, pid: int) -> PlayerStatus:
        m = self._latest.get(pid)
        if m is None:
            return PlayerStatus("none")
        if m.is_played:
            if m.winner_id == pid and m.round == self.n:
                return PlayerStatus("champion", m.round, m)
            if m.winner_id != pid:
                return PlayerStatus("out", m.round, m)
            return PlayerStatus("alive", m.round, m)  # sollte durch Weiterreichen nicht vorkommen
        opp_idx = 1 if m.p1_id == pid else 0
        return PlayerStatus("alive", m.round, m, self.side(m, opp_idx))

    # ------------------------------------------------------------ Nachbarn im Baum

    def feeder(self, m: Match, idx: int) -> Match | None:
        """Das Match, dessen Sieger auf Seite idx (0/1) von m spielt."""
        return self.by_pos.get((m.round - 1, 2 * m.slot + idx))

    def next_match(self, m: Match) -> Match | None:
        return self.by_pos.get((m.round + 1, m.slot // 2))

    def path(self, pid: int, before_round: int) -> list[Match]:
        """Bisherige Matches eines Spielers vor dieser Runde (für 'Weg ins Match')."""
        return sorted((m for m in self.by_pos.values()
                       if m.round < before_round and m.is_played and pid in (m.p1_id, m.p2_id)),
                      key=lambda m: m.round)

    def section_of_match(self, m: Match) -> str:
        if self.n <= 3 or m.round > self.split_round:
            return "finals"
        return str(m.slot // 2 ** (self.split_round - m.round) + 1)
