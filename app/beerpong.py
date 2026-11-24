"""Bierpong: Spiele (Becher zählen), Stats und Anbindung an die K.-o.-Turniere."""

import random
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models
from . import tournaments as tour
from .competitors import competitor_for_user, create_guest

CUP_OPTIONS = (6, 10)


class BeerpongError(ValueError):
    """Meldung für den User."""


# ---------------------------------------------------------------- Spiele


def create_game(db: Session, cups: int, team1: list[int], team2: list[int], created_by: models.User | None,
                names: tuple[str | None, str | None] = (None, None), tournament_match_id: int | None = None,
                commit: bool = True) -> models.BeerpongGame:
    if cups not in CUP_OPTIONS:
        raise BeerpongError("Play with 6 or 10 cups.")
    if not (1 <= len(team1) <= 4 and 1 <= len(team2) <= 4):
        raise BeerpongError("Each team needs 1 to 4 players.")
    if len(set(team1 + team2)) != len(team1) + len(team2):
        raise BeerpongError("Each player can only play on one side.")
    game = models.BeerpongGame(cups=cups, created_by_id=created_by.id if created_by else None,
                               team1_name=names[0], team2_name=names[1], tournament_match_id=tournament_match_id)
    game.players = [models.BeerpongGamePlayer(side=side, position=i, competitor_id=cid)
                    for side, team in ((1, team1), (2, team2)) for i, cid in enumerate(team)]
    db.add(game)
    if commit:
        db.commit()
    else:
        db.flush()
    return game


def can_manage(user: models.User | None, game: models.BeerpongGame) -> bool:
    if user is None or game.status == "abandoned":
        return False
    return (user.is_admin or game.created_by_id == user.id
            or any(p.competitor.user_id == user.id for p in game.players))


def _tournament_of(db: Session, game: models.BeerpongGame):
    if not game.tournament_match_id:
        return None, None
    tm = db.get(models.TournamentMatch, game.tournament_match_id)
    return (db.get(models.Tournament, tm.tournament_id), tm) if tm else (None, None)


def _finish(db: Session, game: models.BeerpongGame) -> None:
    game.status = "finished"
    game.winner_side = 1 if game.hits1 > game.hits2 else 2
    game.finished_at = datetime.now(timezone.utc)
    t, tm = _tournament_of(db, game)
    if tm is not None and not tm.is_played and tm.entry1_id and tm.entry2_id:
        tour.advance_winner(t, tm, tm.entry1_id if game.winner_side == 1 else tm.entry2_id, game.hits1, game.hits2)


def _reopen(db: Session, game: models.BeerpongGame) -> None:
    t, tm = _tournament_of(db, game)
    if tm is not None and tm.is_played:
        try:
            tour.clear_result(db, t, tm, commit=False)
        except tour.TournamentError as e:
            raise BeerpongError(str(e)) from None
    game.status, game.winner_side, game.finished_at = "live", None, None


def add_hit(db: Session, game: models.BeerpongGame, side: int, delta: int, version: int) -> None:
    """Becher getroffen (+1) oder Korrektur (-1). version = Stand, den die Seite kannte (gegen Doppel-Tipps)."""
    if side not in (1, 2) or delta not in (1, -1):
        raise BeerpongError("Invalid input.")
    if game.status == "abandoned":
        raise BeerpongError("This game was abandoned.")
    if version != game.version:
        raise BeerpongError("The game was updated in the meantime – here is the latest score.")
    hits = game.hits1 if side == 1 else game.hits2
    if delta == 1 and (game.status == "finished" or hits >= game.cups):
        raise BeerpongError("The game is already over.")
    if delta == -1 and hits == 0:
        raise BeerpongError("Nothing to take back.")
    if delta == -1 and game.status == "finished":
        _reopen(db, game)
    if side == 1:
        game.hits1 += delta
    else:
        game.hits2 += delta
    game.version += 1
    if max(game.hits1, game.hits2) >= game.cups:
        _finish(db, game)
    db.commit()


def set_final_score(db: Session, game: models.BeerpongGame, hits1: int, hits2: int) -> None:
    """Ergebnis direkt eintragen (Spiel ohne Live-Zählen)."""
    if not (0 <= hits1 <= game.cups and 0 <= hits2 <= game.cups) or hits1 == hits2 or max(hits1, hits2) != game.cups:
        raise BeerpongError(f"The winner hits all {game.cups} cups, the other team fewer.")
    if game.status == "finished":
        _reopen(db, game)
    game.hits1, game.hits2 = hits1, hits2
    game.version += 1
    _finish(db, game)
    db.commit()


def abandon(db: Session, game: models.BeerpongGame) -> None:
    if game.status == "finished":
        _reopen(db, game)
    game.status = "abandoned"
    game.version += 1
    db.commit()


# ---------------------------------------------------------------- Turniere


def entry_team(entry: models.TournamentEntry) -> list[int]:
    return [m.competitor_id for m in entry.members]


def tournament_game(db: Session, tm: models.TournamentMatch) -> models.BeerpongGame | None:
    return db.scalar(select(models.BeerpongGame).where(
        models.BeerpongGame.tournament_match_id == tm.id, models.BeerpongGame.status != "abandoned")
        .order_by(models.BeerpongGame.id.desc()))


def start_tournament_game(db: Session, t: models.Tournament, tm: models.TournamentMatch,
                          user: models.User) -> models.BeerpongGame:
    existing = tournament_game(db, tm)
    if existing is not None and existing.status == "live":
        return existing
    if tm.is_played:
        raise BeerpongError("This match already has a result.")
    if tm.entry1 is None or tm.entry2 is None:
        raise BeerpongError("Both teams of this match are not known yet.")
    return create_game(db, int((t.settings or {}).get("cups", 10)), entry_team(tm.entry1), entry_team(tm.entry2),
                       user, names=(tm.entry1.name, tm.entry2.name), tournament_match_id=tm.id)


def record_tournament_result(db: Session, t: models.Tournament, tm: models.TournamentMatch,
                             hits1: int, hits2: int, user: models.User) -> None:
    """Ergebnis eines Turnier-Matches von Hand: legt (oder aktualisiert) das zugehörige Spiel an."""
    if tm.entry1 is None or tm.entry2 is None or tm.bye:
        raise BeerpongError("Both teams of this match are not known yet.")
    if tm.is_played and not tour.can_change(t, tm):
        raise BeerpongError("The next match already has a result – reset that one first.")
    game = tournament_game(db, tm)
    if game is None:
        game = create_game(db, int((t.settings or {}).get("cups", 10)), entry_team(tm.entry1), entry_team(tm.entry2),
                           user, names=(tm.entry1.name, tm.entry2.name), tournament_match_id=tm.id, commit=False)
    set_final_score(db, game, hits1, hits2)


def reset_tournament_match(db: Session, t: models.Tournament, tm: models.TournamentMatch) -> None:
    tour.clear_result(db, t, tm, commit=False)
    game = tournament_game(db, tm)
    if game is not None:
        game.status = "abandoned"  # zählt nicht mehr für die Stats; neues Spiel möglich
        game.version += 1
    db.commit()


def parse_teams(db: Session, text: str) -> tuple[list[list[int]], list[str | None]]:
    """Feste Teams aus Textzeilen: "Teamname: Olli, Kevin" oder nur "Olli, Kevin".
    Namen von Mitgliedern/Gästen werden erkannt, unbekannte Namen werden neue Gäste."""
    teams, names = [], []
    for line in [ln.strip() for ln in text.splitlines() if ln.strip()]:
        team_name, _, members = line.rpartition(":")
        people = [p.strip() for p in members.replace("&", ",").replace("+", ",").split(",") if p.strip()]
        if not people:
            raise BeerpongError(f"No players in the line “{line}”.")
        ids = [_find_or_create(db, p) for p in people]
        teams.append(ids)
        names.append(" ".join(team_name.split()) or None)
    return teams, names


def _find_or_create(db: Session, name: str) -> int:
    low = name.lower()
    user = db.scalar(select(models.User).where(func.lower(models.User.username) == low))
    if user is not None:
        return competitor_for_user(db, user).id
    guest = db.scalar(select(models.Competitor).where(
        models.Competitor.user_id.is_(None), func.lower(models.Competitor.name) == low))
    return guest.id if guest else create_guest(db, name).id


def random_pairs(ids: list[int]) -> list[list[int]]:
    if len(ids) < 4 or len(ids) % 2:
        raise BeerpongError("Random teams of 2 need an even number of players (at least 4).")
    ids = list(ids)
    random.shuffle(ids)
    return [ids[i:i + 2] for i in range(0, len(ids), 2)]


# ---------------------------------------------------------------- Stats


@dataclass
class BeerpongStats:
    competitor_id: int
    games: int = 0
    wins: int = 0
    cups_for: int = 0
    cups_against: int = 0

    @property
    def win_pct(self) -> float | None:
        return 100 * self.wins / self.games if self.games else None

    @property
    def cups_per_game(self) -> float | None:
        return self.cups_for / self.games if self.games else None

    @property
    def diff_per_game(self) -> float | None:
        return (self.cups_for - self.cups_against) / self.games if self.games else None


def compute_stats(db: Session, competitor_ids: list[int] | None = None) -> dict[int, BeerpongStats]:
    """Nur beendete Spiele. Getroffene Becher zählen für jedes Teammitglied."""
    stats: dict[int, BeerpongStats] = {}
    for g in db.scalars(select(models.BeerpongGame).where(models.BeerpongGame.status == "finished")):
        for p in g.players:
            if competitor_ids is not None and p.competitor_id not in competitor_ids:
                continue
            s = stats.setdefault(p.competitor_id, BeerpongStats(p.competitor_id))
            s.games += 1
            s.wins += g.winner_side == p.side
            s.cups_for += g.hits1 if p.side == 1 else g.hits2
            s.cups_against += g.hits2 if p.side == 1 else g.hits1
    return stats


# ---------------------------------------------------------------- Vergleich zweier Spieler

COMPARE_ROWS = (
    ("win_pct", "Win rate", True, "pct"),
    ("games", "Games played", None, "int"),
    ("wins", "Games won", True, "int"),
    ("cups_per_game", "Cups per game", True, "dec"),
    ("diff_per_game", "Cup difference per game", True, "signed"),
)


def compare_rows(a: BeerpongStats | None, b: BeerpongStats | None) -> list[dict]:
    rows = []
    for key, label, higher, fmt in COMPARE_ROWS:
        va = getattr(a, key) if a else None
        vb = getattr(b, key) if b else None
        winner = None
        if higher is not None and va is not None and vb is not None and va != vb:
            winner = "a" if (va > vb) == higher else "b"
        rows.append({"label": label, "a": va, "b": vb, "fmt": fmt, "winner": winner})
    return rows


@dataclass
class Rivalry:
    against: list[models.BeerpongGame]  # a und b in verschiedenen Teams
    together: list[models.BeerpongGame]  # a und b im selben Team
    wins_a: int = 0
    wins_b: int = 0
    cups_a: int = 0
    cups_b: int = 0
    together_wins: int = 0


def rivalry(db: Session, a: int, b: int) -> Rivalry:
    games = db.scalars(select(models.BeerpongGame).where(models.BeerpongGame.status == "finished")
                       .order_by(models.BeerpongGame.created_at.desc(), models.BeerpongGame.id.desc())).all()
    r = Rivalry(against=[], together=[])
    for g in games:
        side = {p.competitor_id: p.side for p in g.players}
        if a not in side or b not in side:
            continue
        if side[a] == side[b]:
            r.together.append(g)
            r.together_wins += g.winner_side == side[a]
        else:
            r.against.append(g)
            r.wins_a += g.winner_side == side[a]
            r.wins_b += g.winner_side == side[b]
            r.cups_a += g.hits1 if side[a] == 1 else g.hits2
            r.cups_b += g.hits1 if side[b] == 1 else g.hits2
    return r
