"""Elo-Wertung und Formkurve - wie die Stats immer frisch aus den Spielen berechnet (nichts gespeichert).

Elo: jeder startet bei 1000. Nach jedem beendeten Spiel (X01 und Partyspiele, ab 2 Seiten) gewinnt der
Sieger Punkte von jedem Verlierer: K * (1 - erwartetes Ergebnis), erwartet = 1 / (1 + 10^((Rb - Ra) / 400)).
Bei mehr als zwei Seiten wird K auf die Gegner aufgeteilt. Doppel: das Team zählt mit dem Schnitt seiner
beiden Spieler, beide bekommen dieselbe Änderung. Wer weniger als PROVISIONAL Spiele hat, ist "vorläufig".
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models

START = 1000.0
K = 32.0
PROVISIONAL = 5


def aware(dt: datetime | None) -> datetime:
    """SQLite liefert Zeiten ohne Zeitzone - für Vergleiche immer UTC-bewusst machen."""
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def data_version(db: Session) -> tuple:
    """Ändert sich, sobald sich an Spielen etwas ändert (neue/gelöschte Aufnahme, Spielende, Abbruch,
    Turniersieg, Gast mit Konto verknüpft) - Schlüssel für den Zwischenspeicher unten."""
    v = db.execute(select(func.count(models.DartsVisit.id), func.max(models.DartsVisit.id),
                          func.coalesce(func.sum(models.DartsVisit.competitor_id), 0),
                          func.coalesce(func.sum(models.DartsVisit.score), 0))).one()
    g = db.execute(select(func.count(models.DartsGame.id), func.max(models.DartsGame.id),
                          func.count(models.DartsGame.finished_at),
                          func.coalesce(func.sum(models.DartsGame.winner_id), 0))
                   .where(models.DartsGame.status != "abandoned")).one()
    p = db.scalar(select(func.coalesce(func.sum(models.DartsGamePlayer.competitor_id), 0)))
    t = db.execute(select(func.count(models.Tournament.id), func.coalesce(func.sum(models.Tournament.winner_entry_id), 0))
                   .where(models.Tournament.winner_entry_id.is_not(None))).one()
    return (db.get_bind().url.render_as_string(), *v, *g, p, *t)


_cache: dict[str, tuple] = {}


def cached(db: Session, name: str, compute):
    """Ergebnis von compute() wiederverwenden, solange sich die Daten nicht geändert haben (pro Prozess)."""
    version = data_version(db)
    hit = _cache.get(name)
    if hit and hit[0] == version:
        return hit[1]
    value = compute()
    _cache[name] = (version, value)
    return value


def finished_games(db: Session) -> list[models.DartsGame]:
    """Alle beendeten Spiele in der Reihenfolge, in der sie zu Ende gingen."""
    games = db.scalars(select(models.DartsGame).where(models.DartsGame.status == "finished")).all()
    return sorted(games, key=lambda g: (aware(g.finished_at or g.created_at), g.id))


@dataclass
class EloPoint:
    at: datetime
    rating: float
    delta: float
    game_id: int


@dataclass
class Elo:
    ratings: dict[int, float] = field(default_factory=dict)
    games: dict[int, int] = field(default_factory=dict)
    history: dict[int, list[EloPoint]] = field(default_factory=dict)
    deltas: dict[int, dict[int, float]] = field(default_factory=dict)  # game_id -> {competitor_id: Änderung}

    def rating(self, cid: int) -> float:
        return self.ratings.get(cid, START)

    def provisional(self, cid: int) -> bool:
        return self.games.get(cid, 0) < PROVISIONAL

    def rank(self, cid: int) -> int | None:
        """Platz unter allen, die schon gewertet sind (vorläufige zählen nicht mit)."""
        if cid not in self.ratings or self.provisional(cid):
            return None
        ranked = sorted((r for c, r in self.ratings.items() if not self.provisional(c)), reverse=True)
        return ranked.index(self.ratings[cid]) + 1


def expected(ra: float, rb: float) -> float:
    return 1 / (1 + 10 ** ((rb - ra) / 400))


def compute_elo(db: Session, games: list[models.DartsGame] | None = None) -> Elo:
    """Elo aller Spieler (ohne games: aus dem Zwischenspeicher, falls sich nichts geändert hat)."""
    if games is None:
        return cached(db, "elo", lambda: _compute_elo(finished_games(db)))
    return _compute_elo(games)


def _compute_elo(games: list[models.DartsGame]) -> Elo:
    elo = Elo()
    for g in games:
        n = g.n_sides
        win = g.winning_side
        if n < 2 or win is None:
            continue  # Solo-Training zählt nicht
        sides = [[p.competitor_id for p in g.side_players(s)] for s in range(n)]
        side_rating = [sum(elo.rating(c) for c in side) / len(side) for side in sides]
        change = [0.0] * n
        k = K / (n - 1)
        for s in range(n):
            if s == win:
                continue
            d = k * (1 - expected(side_rating[win], side_rating[s]))
            change[win] += d
            change[s] -= d
        at = aware(g.finished_at or g.created_at)
        elo.deltas[g.id] = {}
        for s, side in enumerate(sides):
            for c in side:
                elo.ratings[c] = elo.rating(c) + change[s]
                elo.games[c] = elo.games.get(c, 0) + 1
                elo.history.setdefault(c, []).append(EloPoint(at, elo.ratings[c], change[s], g.id))
                elo.deltas[g.id][c] = change[s]
    return elo


@dataclass
class FormPoint:
    at: datetime
    average: float
    game_id: int
    won: bool


def form_curve(db: Session, competitor_id: int, limit: int = 30) -> list[FormPoint]:
    """3-Dart-Average pro beendetem X01-Spiel, die letzten `limit` Spiele, älteste zuerst."""
    game_ids = select(models.DartsGamePlayer.game_id).where(models.DartsGamePlayer.competitor_id == competitor_id)
    games = db.scalars(select(models.DartsGame).where(
        models.DartsGame.id.in_(game_ids), models.DartsGame.status == "finished", models.DartsGame.mode == "x01")).all()
    games = sorted(games, key=lambda g: (aware(g.finished_at or g.created_at), g.id))[-limit:]
    out = []
    for g in games:
        vs = [v for v in g.visits if v.competitor_id == competitor_id]
        darts = sum(v.darts for v in vs)
        if darts:
            out.append(FormPoint(aware(g.finished_at or g.created_at), 3 * sum(v.score for v in vs) / darts, g.id,
                                 g.won_by(competitor_id)))
    return out
