"""Turniere (gemeinsam für Darts und Bierpong): K.-o. oder Gruppenphase + K.-o.

K.-o.: Setzliste wie im Profisport - 1 gegen den Letzten, 2 gegen den Vorletzten ... so verteilt, dass sich
die Topgesetzten erst spät treffen. Ist die Teilnehmerzahl keine Zweierpotenz, bekommen die
Topgesetzten ein Freilos (bye) und stehen direkt in Runde 2.

Gruppenphase: Einträge werden nach Setzliste "in Schlangenlinie" auf die Gruppen verteilt (A B C C B A ...),
in jeder Gruppe spielt jeder gegen jeden. Tabelle: Siege, dann Differenz (Legs bzw. Becher), dann
erzielte Legs/Becher, dann direkter Vergleich. Sind alle Gruppenspiele gespielt, entsteht der K.-o.-Baum
automatisch - bei zwei Qualifikanten pro Gruppe über Kreuz (A1-B2, B1-A2), damit sich Gruppengegner
nicht gleich wiedersehen.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models


class TournamentError(ValueError):
    """Meldung für den User."""


GROUP_LETTERS = "ABCDEFGHIJKLMNOP"


def group_label(group_no: int) -> str:
    return f"Group {GROUP_LETTERS[group_no]}"


def bracket_order(size: int) -> list[int]:
    """Setzplätze in Baum-Reihenfolge, z. B. 8 -> [1, 8, 4, 5, 2, 7, 3, 6]."""
    order = [1, 2]
    while len(order) < size:
        n = 2 * len(order) + 1
        order = [x for s in order for x in (s, n - s)]
    return order[:size] if size > 1 else [1]


def round_title(round_no: int, num_rounds: int) -> str:
    left = num_rounds - round_no
    return {0: "Final", 1: "Semi-finals", 2: "Quarter-finals"}.get(left, f"Round of {2 ** (left + 1)}")


def match_title(t: models.Tournament, m: models.TournamentMatch) -> str:
    return group_label(m.group_no) if m.group_no is not None else round_title(m.round, t.num_rounds)


def is_final(t: models.Tournament, m: models.TournamentMatch) -> bool:
    return m.group_no is None and t.num_rounds > 0 and m.round == t.num_rounds


def suggested_groups(n: int) -> int:
    """Vorschlag: Gruppen mit 3-5 Einträgen."""
    return max(1, min(len(GROUP_LETTERS), round(n / 4)))


# ---------------------------------------------------------------- Anlegen


def create_tournament(db: Session, sport: str, name: str, entries: list[list[int]], settings: dict,
                      created_by: models.User | None, shuffle: bool = False,
                      entry_names: list[str | None] | None = None,
                      groups: int | None = None, advance: int = 2) -> models.Tournament:
    """entries = Teilnehmer-ID-Listen (1 pro Eintrag bei Darts, mehrere bei Bierpong-Teams), in Setz-Reihenfolge.
    groups = Anzahl Gruppen (None = reines K.-o.), advance = Qualifikanten pro Gruppe."""
    name = " ".join(name.split())
    if not 1 <= len(name) <= 80:
        raise TournamentError("The tournament needs a name (max. 80 characters).")
    n = len(entries)
    if not 2 <= n <= 64:
        raise TournamentError("A tournament needs 2 to 64 entries.")
    flat = [cid for e in entries for cid in e]
    if len(flat) != len(set(flat)):
        raise TournamentError("Each player can only be entered once.")
    if groups is not None:
        if not 1 <= groups <= len(GROUP_LETTERS):
            raise TournamentError(f"Choose 1 to {len(GROUP_LETTERS)} groups.")
        if n < 2 * groups:
            raise TournamentError(f"{groups} groups need at least {2 * groups} entries (2 per group).")
        smallest = n // groups
        if not 1 <= advance < smallest:
            raise TournamentError(f"With groups of {smallest} at most {smallest - 1} can go through per group.")
        if groups * advance < 2:
            raise TournamentError("At least two entries must reach the knockout stage.")

    names = list(entry_names or [None] * n)
    order = list(range(n))
    if shuffle:
        random.shuffle(order)
    settings = dict(settings)
    if groups is not None:
        settings.update(format="groups", groups=groups, advance=advance)

    t = models.Tournament(sport=sport, name=name, settings=settings,
                          created_by_id=created_by.id if created_by else None)
    t.entries = [models.TournamentEntry(seed=seed, name=names[i], members=[
                     models.TournamentEntryMember(position=p, competitor_id=cid) for p, cid in enumerate(entries[i])])
                 for seed, i in enumerate(order, start=1)]
    db.add(t)
    db.flush()

    if groups is None:
        _build_bracket(t, _seeded_slots(t.entries))
    else:
        _build_groups(t, groups)
    db.commit()
    db.refresh(t)
    return t


def _seeded_slots(entries: list[models.TournamentEntry]) -> list[models.TournamentEntry | None]:
    """Einträge (beste zuerst) auf die Plätze von Runde 1 verteilen; None = Freilos."""
    size = 1
    while size < len(entries):
        size *= 2
    return [entries[s - 1] if s <= len(entries) else None for s in bracket_order(size)]


def _build_bracket(t: models.Tournament, slots: list[models.TournamentEntry | None]) -> None:
    """K.-o.-Baum aus den Plätzen von Runde 1 (Länge = Zweierpotenz) anlegen, Freilose auflösen."""
    size = len(slots)
    rounds = size.bit_length() - 1
    first = []
    for r in range(1, rounds + 1):
        for s in range(size >> r):
            m = models.TournamentMatch(round=r, slot=s)
            if r == 1:
                a, b = slots[2 * s], slots[2 * s + 1]
                m.entry1_id, m.entry2_id = (a.id if a else None), (b.id if b else None)
                first.append(m)
            t.matches.append(m)
    for m in first:
        if (m.entry1_id is None) != (m.entry2_id is None):  # Freilos
            m.bye = True
            advance_winner(t, m, m.entry1_id or m.entry2_id, 0, 0)


def _round_robin(items: list) -> list[tuple]:
    """Jeder gegen jeden, nach Spieltagen geordnet (Kreis-Methode)."""
    xs = list(items) + ([None] if len(items) % 2 else [])
    n = len(xs)
    pairs = []
    for _ in range(n - 1):
        for i in range(n // 2):
            a, b = xs[i], xs[n - 1 - i]
            if a is not None and b is not None:
                pairs.append((a, b))
        xs = [xs[0], xs[-1], *xs[1:-1]]
    return pairs


def _build_groups(t: models.Tournament, groups: int) -> None:
    by_group: dict[int, list[models.TournamentEntry]] = {g: [] for g in range(groups)}
    for i, e in enumerate(t.entries):  # Schlangenlinie: A B C C B A A B C ...
        lap, pos = divmod(i, groups)
        e.group_no = pos if lap % 2 == 0 else groups - 1 - pos
        by_group[e.group_no].append(e)
    slot = 0
    for g, members in by_group.items():
        for a, b in _round_robin(members):
            t.matches.append(models.TournamentMatch(round=0, slot=slot, group_no=g, entry1_id=a.id, entry2_id=b.id))
            slot += 1


# ---------------------------------------------------------------- Ergebnisse


def _match_at(t: models.Tournament, round_no: int, slot: int) -> models.TournamentMatch | None:
    return next((m for m in t.matches if m.round == round_no and m.slot == slot and m.group_no is None), None)


def next_match(t: models.Tournament, m: models.TournamentMatch) -> models.TournamentMatch | None:
    if m.group_no is not None:
        return None
    return _match_at(t, m.round + 1, m.slot // 2)


def knockout_started(t: models.Tournament) -> bool:
    return bool(t.ko_matches)


def advance_winner(t: models.Tournament, m: models.TournamentMatch, winner_id: int, s1: int, s2: int) -> None:
    """Ergebnis setzen. K.-o.: Sieger rückt weiter. Gruppe: letztes Gruppenspiel -> K.-o.-Baum entsteht."""
    m.winner_id, m.score1, m.score2 = winner_id, s1, s2
    m.updated_at = datetime.now(timezone.utc)
    if m.group_no is not None:
        if not knockout_started(t) and all(x.is_played for x in t.group_matches):
            _build_bracket(t, _knockout_slots(t))
        return
    nxt = next_match(t, m)
    if nxt is None:  # Finale
        t.status, t.winner_entry_id, t.finished_at = "finished", winner_id, datetime.now(timezone.utc)
    elif m.slot % 2 == 0:
        nxt.entry1_id = winner_id
    else:
        nxt.entry2_id = winner_id


def can_change(t: models.Tournament, m: models.TournamentMatch) -> bool:
    """K.-o.: solange das Folgematch kein Ergebnis hat. Gruppe: solange der K.-o. nicht begonnen hat."""
    if m.bye:
        return False
    if m.group_no is not None:
        return not knockout_started(t)
    nxt = next_match(t, m)
    return nxt is None or not nxt.is_played


def _locked_reason(t: models.Tournament, m: models.TournamentMatch) -> str:
    if m.group_no is not None:
        return "The knockout stage has already started – reset it first."
    return "The next match already has a result – reset that one first."


def set_result(db: Session, t: models.Tournament, m: models.TournamentMatch, score1: int, score2: int) -> None:
    """Ergebnis eintragen (Legs bzw. Becher)."""
    if m.entry1_id is None or m.entry2_id is None:
        raise TournamentError("Both sides of this match are not known yet.")
    if m.is_played and not can_change(t, m):
        raise TournamentError(_locked_reason(t, m))
    if score1 < 0 or score2 < 0 or score1 == score2:
        raise TournamentError("Enter a result with a winner (no draws).")
    advance_winner(t, m, m.entry1_id if score1 > score2 else m.entry2_id, score1, score2)
    db.commit()


def clear_result(db: Session, t: models.Tournament, m: models.TournamentMatch, commit: bool = True) -> None:
    if not m.is_played:
        return
    if not can_change(t, m):
        raise TournamentError(_locked_reason(t, m))
    if m.group_no is None:
        nxt = next_match(t, m)
        if nxt is None:
            t.status, t.winner_entry_id, t.finished_at = "running", None, None
        elif m.slot % 2 == 0:
            nxt.entry1_id = None
        else:
            nxt.entry2_id = None
    m.winner_id, m.score1, m.score2, m.updated_at = None, 0, 0, datetime.now(timezone.utc)
    if commit:
        db.commit()


def reset_knockout(db: Session, t: models.Tournament) -> None:
    """K.-o.-Baum wieder entfernen (nur mit Gruppenphase und solange dort nichts gespielt ist)."""
    if not t.has_groups or not knockout_started(t):
        raise TournamentError("There is no knockout stage to reset.")
    if any(m.is_played and not m.bye for m in t.ko_matches):
        raise TournamentError("Knockout matches already have results – reset those first.")
    for m in t.ko_matches:
        t.matches.remove(m)
        db.delete(m)
    t.status, t.winner_entry_id, t.finished_at = "running", None, None
    db.commit()


# ---------------------------------------------------------------- Gruppentabellen


@dataclass
class Standing:
    entry: models.TournamentEntry
    played: int = 0
    won: int = 0
    lost: int = 0
    score_for: int = 0
    score_against: int = 0
    beaten: set = field(default_factory=set)  # IDs der geschlagenen Gegner (direkter Vergleich)

    @property
    def diff(self) -> int:
        return self.score_for - self.score_against


def standings(t: models.Tournament) -> dict[int, list[Standing]]:
    """Gruppentabellen, bereits sortiert."""
    table: dict[int, dict[int, Standing]] = {}
    for e in t.entries:
        if e.group_no is not None:
            table.setdefault(e.group_no, {})[e.id] = Standing(e)
    for m in t.group_matches:
        if not m.is_played:
            continue
        a, b = table[m.group_no][m.entry1_id], table[m.group_no][m.entry2_id]
        for me, other, sf, sa in ((a, b, m.score1, m.score2), (b, a, m.score2, m.score1)):
            me.played += 1
            me.score_for += sf
            me.score_against += sa
            if m.winner_id == me.entry.id:
                me.won += 1
                me.beaten.add(other.entry.id)
            else:
                me.lost += 1
    out = {}
    for g, rows in sorted(table.items()):
        rows = sorted(rows.values(), key=lambda s: (-s.won, -s.diff, -s.score_for, s.entry.seed))
        # Direkter Vergleich bei Gleichstand in Siegen, Differenz und erzielten Punkten (zwei Einträge)
        for i in range(len(rows) - 1):
            x, y = rows[i], rows[i + 1]
            if (x.won, x.diff, x.score_for) == (y.won, y.diff, y.score_for) and x.entry.id in y.beaten:
                rows[i], rows[i + 1] = y, x
        out[g] = rows
    return out


def _knockout_slots(t: models.Tournament) -> list[models.TournamentEntry | None]:
    advance = int(t.settings.get("advance", 2))
    table = standings(t)
    groups = [table[g] for g in sorted(table)]
    q = [[rows[r].entry for r in range(min(advance, len(rows)))] for rows in groups]
    n_groups = len(q)
    power_of_two = n_groups >= 2 and n_groups & (n_groups - 1) == 0
    if advance == 2 and power_of_two:
        # Über Kreuz: A1-B2 und C1-D2 in der oberen Hälfte, B1-A2 und D1-C2 in der unteren
        top = [x for i in range(0, n_groups, 2) for x in (q[i][0], q[i + 1][1])]
        bottom = [x for i in range(0, n_groups, 2) for x in (q[i + 1][0], q[i][1])]
        return top + bottom
    # Sonst: erst alle Gruppensieger (nach Bilanz), dann alle Zweiten ... in die normale Setzliste
    by_rank = []
    for r in range(advance):
        rank_rows = [rows[r] for rows in groups if r < len(rows)]
        by_rank += [s.entry for s in sorted(rank_rows, key=lambda s: (-s.won, -s.diff, -s.score_for))]
    return _seeded_slots(by_rank)


# ---------------------------------------------------------------- Anzeige & Rechte


def can_organize(user: models.User | None, t: models.Tournament) -> bool:
    return user is not None and (user.is_admin or t.created_by_id == user.id)


def entry_by_id(t: models.Tournament, entry_id: int | None) -> models.TournamentEntry | None:
    return next((e for e in t.entries if e.id == entry_id), None)


def columns(t: models.Tournament) -> list[dict]:
    """Für die Baum-Anzeige: K.-o.-Runden als Spalten, Matches paarweise gruppiert (für die Verbindungslinien)."""
    n = t.num_rounds
    cols = []
    for r in range(1, n + 1):
        ms = sorted((m for m in t.ko_matches if m.round == r), key=lambda m: m.slot)
        cols.append({"round": r, "title": round_title(r, n), "groups": [ms[i:i + 2] for i in range(0, len(ms), 2)]})
    return cols


def group_view(t: models.Tournament) -> list[dict]:
    """Für die Anzeige: pro Gruppe Tabelle (mit Markierung der Qualifikanten) und Spiele."""
    advance = int((t.settings or {}).get("advance", 2))
    table = standings(t)
    return [{"no": g, "label": group_label(g), "rows": rows, "advance": advance,
             "matches": [m for m in t.group_matches if m.group_no == g]}
            for g, rows in table.items()]


def running(db: Session, sport: str, limit: int = 3) -> list[models.Tournament]:
    return list(db.scalars(select(models.Tournament).where(models.Tournament.sport == sport,
                                                           models.Tournament.status == "running")
                           .order_by(models.Tournament.created_at.desc()).limit(limit)))


# ---------------------------------------------------------------- Turnier-Stats pro Teilnehmer


@dataclass
class EntryResult:
    entry: models.TournamentEntry
    played: int = 0
    won: int = 0
    lost: int = 0
    score_for: int = 0
    score_against: int = 0
    out_round: int | None = None  # K.-o.-Runde, in der verloren wurde
    out_in_groups: bool = False
    place: str = "Still in"
    rank: int = 0  # für die Sortierung: 0 = Champion, kleiner = besser

    @property
    def diff(self) -> int:
        return self.score_for - self.score_against


def entry_results(t: models.Tournament) -> list[EntryResult]:
    """Bilanz und Platzierung jedes Eintrags über das ganze Turnier (Gruppe + K.-o., ohne Freilose)."""
    res = {e.id: EntryResult(e) for e in t.entries}
    for m in t.matches:
        if not m.is_played or m.bye:
            continue
        for eid, sf, sa in ((m.entry1_id, m.score1, m.score2), (m.entry2_id, m.score2, m.score1)):
            r = res[eid]
            r.played += 1
            r.score_for += sf
            r.score_against += sa
            if m.winner_id == eid:
                r.won += 1
            else:
                r.lost += 1
                if m.group_no is None:
                    r.out_round = m.round
    n = t.num_rounds
    in_ko = {eid for m in t.ko_matches for eid in (m.entry1_id, m.entry2_id) if eid}
    for r in res.values():
        if t.winner_entry_id == r.entry.id:
            r.place, r.rank = "Champion", 0
        elif r.out_round is not None:
            left = n - r.out_round  # 0 = im Finale verloren
            r.place = "Runner-up" if left == 0 else round_title(r.out_round, n).replace("Round of", "Last")
            r.rank = 1 + left
        elif t.has_groups and knockout_started(t) and r.entry.id not in in_ko:
            r.out_in_groups, r.place, r.rank = True, "Group stage", 100
        else:
            r.place, r.rank = "Still in", 50
    return sorted(res.values(), key=lambda r: (r.rank, -r.won, -r.diff, -r.score_for, r.entry.seed))


def organizes_match(db: Session, match_id: int | None, user: models.User | None) -> bool:
    """Ist der User Organisator des Turniers, zu dem dieses Match gehört?"""
    if not match_id or user is None:
        return False
    tm = db.get(models.TournamentMatch, match_id)
    return tm is not None and can_organize(user, db.get(models.Tournament, tm.tournament_id))


def hall_of_fame(db: Session, sport: str) -> list[tuple[models.Competitor, int]]:
    """Turniersiege pro Teilnehmer (bei Teams zählt der Titel für jedes Mitglied)."""
    titles: dict[int, int] = {}
    people: dict[int, models.Competitor] = {}
    for t in db.scalars(select(models.Tournament).where(models.Tournament.sport == sport,
                                                        models.Tournament.status == "finished")):
        champ = entry_by_id(t, t.winner_entry_id)
        for c in champ.competitors if champ else []:
            titles[c.id] = titles.get(c.id, 0) + 1
            people[c.id] = c
    return sorted(((people[cid], n) for cid, n in titles.items()), key=lambda x: (-x[1], x[0].display_name.lower()))
