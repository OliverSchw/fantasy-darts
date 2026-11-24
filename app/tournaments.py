"""K.-o.-Turniere (gemeinsam für Darts und Bierpong).

Setzliste wie im Profisport: 1 gegen den Letzten, 2 gegen den Vorletzten ... so verteilt, dass sich
die Topgesetzten erst spät treffen. Ist die Teilnehmerzahl keine Zweierpotenz, bekommen die
Topgesetzten ein Freilos (bye) und stehen direkt in Runde 2.
"""

import random
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import models


class TournamentError(ValueError):
    """Meldung für den User."""


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


def create_tournament(db: Session, sport: str, name: str, entries: list[list[int]], settings: dict,
                      created_by: models.User | None, shuffle: bool = False,
                      entry_names: list[str | None] | None = None) -> models.Tournament:
    """entries = Liste von Teilnehmer-ID-Listen (1 pro Eintrag bei Darts, 2 bei Bierpong-Teams), in Setz-Reihenfolge."""
    name = " ".join(name.split())
    if not 1 <= len(name) <= 80:
        raise TournamentError("The tournament needs a name (max. 80 characters).")
    if not 2 <= len(entries) <= 64:
        raise TournamentError("A tournament needs 2 to 64 entries.")
    flat = [cid for e in entries for cid in e]
    if len(flat) != len(set(flat)):
        raise TournamentError("Each player can only be entered once.")
    names = list(entry_names or [None] * len(entries))
    order = list(range(len(entries)))
    if shuffle:
        random.shuffle(order)

    t = models.Tournament(sport=sport, name=name, settings=settings,
                          created_by_id=created_by.id if created_by else None)
    t.entries = [models.TournamentEntry(seed=seed, name=names[i], members=[
                     models.TournamentEntryMember(position=p, competitor_id=cid) for p, cid in enumerate(entries[i])])
                 for seed, i in enumerate(order, start=1)]
    db.add(t)
    db.flush()

    n = len(entries)
    size = 1
    while size < n:
        size *= 2
    rounds = size.bit_length() - 1
    by_seed = {e.seed: e for e in t.entries}
    pos = bracket_order(size)
    for r in range(1, rounds + 1):
        for s in range(size >> r):
            m = models.TournamentMatch(round=r, slot=s)
            if r == 1:
                m.entry1_id = by_seed[pos[2 * s]].id if pos[2 * s] <= n else None
                m.entry2_id = by_seed[pos[2 * s + 1]].id if pos[2 * s + 1] <= n else None
            t.matches.append(m)
    db.flush()
    for m in [m for m in t.matches if m.round == 1]:
        if (m.entry1_id is None) != (m.entry2_id is None):  # Freilos
            m.bye = True
            advance_winner(t, m, m.entry1_id or m.entry2_id, 0, 0)
    db.commit()
    db.refresh(t)
    return t


def _match_at(t: models.Tournament, round_no: int, slot: int) -> models.TournamentMatch | None:
    return next((m for m in t.matches if m.round == round_no and m.slot == slot), None)


def next_match(t: models.Tournament, m: models.TournamentMatch) -> models.TournamentMatch | None:
    return _match_at(t, m.round + 1, m.slot // 2)


def advance_winner(t: models.Tournament, m: models.TournamentMatch, winner_id: int, s1: int, s2: int) -> None:
    m.winner_id, m.score1, m.score2 = winner_id, s1, s2
    m.updated_at = datetime.now(timezone.utc)
    nxt = next_match(t, m)
    if nxt is None:  # Finale
        t.status, t.winner_entry_id, t.finished_at = "finished", winner_id, datetime.now(timezone.utc)
    elif m.slot % 2 == 0:
        nxt.entry1_id = winner_id
    else:
        nxt.entry2_id = winner_id


def can_change(t: models.Tournament, m: models.TournamentMatch) -> bool:
    """Ein Ergebnis darf geändert werden, solange das Folgematch noch kein Ergebnis hat."""
    nxt = next_match(t, m)
    return not m.bye and (nxt is None or not nxt.is_played)


def set_result(db: Session, t: models.Tournament, m: models.TournamentMatch, score1: int, score2: int) -> None:
    """Ergebnis eintragen (Legs bzw. Becher). Der Sieger rückt automatisch in die nächste Runde."""
    if m.entry1_id is None or m.entry2_id is None:
        raise TournamentError("Both sides of this match are not known yet.")
    if m.is_played and not can_change(t, m):
        raise TournamentError("The next match already has a result – reset that one first.")
    if score1 < 0 or score2 < 0 or score1 == score2:
        raise TournamentError("Enter a result with a winner (no draws).")
    advance_winner(t, m, m.entry1_id if score1 > score2 else m.entry2_id, score1, score2)
    db.commit()


def clear_result(db: Session, t: models.Tournament, m: models.TournamentMatch, commit: bool = True) -> None:
    if not m.is_played:
        return
    if not can_change(t, m):
        raise TournamentError("The next match already has a result – reset that one first.")
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


def can_organize(user: models.User | None, t: models.Tournament) -> bool:
    return user is not None and (user.is_admin or t.created_by_id == user.id)


def entry_by_id(t: models.Tournament, entry_id: int | None) -> models.TournamentEntry | None:
    return next((e for e in t.entries if e.id == entry_id), None)


def columns(t: models.Tournament) -> list[dict]:
    """Für die Baum-Anzeige: Runden als Spalten, Matches paarweise gruppiert (für die Verbindungslinien)."""
    n = t.num_rounds
    cols = []
    for r in range(1, n + 1):
        ms = sorted((m for m in t.matches if m.round == r), key=lambda m: m.slot)
        cols.append({"round": r, "title": round_title(r, n), "groups": [ms[i:i + 2] for i in range(0, len(ms), 2)]})
    return cols
