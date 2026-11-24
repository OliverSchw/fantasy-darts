"""Darts-Statistik pro Teilnehmer - immer frisch aus den Aufnahmen berechnet (nichts gespeichert).

Abgebrochene Spiele zählen nicht. Laufende Spiele zählen bei Würfen mit, aber nicht bei Siegen.
"""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from .checkouts import is_finishable


@dataclass
class PlayerStats:
    competitor_id: int
    games: int = 0  # beendete Spiele
    wins: int = 0
    legs: int = 0  # Legs, in denen geworfen wurde
    legs_won: int = 0
    darts: int = 0
    points: int = 0
    first9_darts: int = 0
    first9_points: int = 0
    tons: int = 0  # 100-139
    ton40: int = 0  # 140-179
    max180: int = 0
    high_finish: int = 0
    best_leg: int | None = None  # wenigste Darts für ein gewonnenes Leg
    checkout_chances: int = 0  # Aufnahmen, die auf einem ausmachbaren Rest begonnen haben
    checkouts: int = 0

    @property
    def average(self) -> float | None:
        return 3 * self.points / self.darts if self.darts else None

    @property
    def first9(self) -> float | None:
        return 3 * self.first9_points / self.first9_darts if self.first9_darts else None

    @property
    def checkout_pct(self) -> float | None:
        return 100 * self.checkouts / self.checkout_chances if self.checkout_chances else None

    @property
    def win_pct(self) -> float | None:
        return 100 * self.wins / self.games if self.games else None


def compute_stats(db: Session, competitor_ids: list[int] | None = None,
                  game_ids: list[int] | None = None) -> dict[int, PlayerStats]:
    """Stats für alle (oder die angegebenen) Teilnehmer, optional nur aus bestimmten Spielen."""
    q = (select(models.DartsVisit)
         .join(models.DartsGame, models.DartsGame.id == models.DartsVisit.game_id)
         .where(models.DartsGame.status != "abandoned")
         .order_by(models.DartsVisit.game_id, models.DartsVisit.seq))
    if competitor_ids is not None:
        q = q.where(models.DartsVisit.competitor_id.in_(competitor_ids))
    if game_ids is not None:
        q = q.where(models.DartsVisit.game_id.in_(game_ids))

    stats: dict[int, PlayerStats] = {}
    leg_darts: dict[tuple, int] = defaultdict(int)  # (game, leg, competitor) -> Darts
    leg_visits: dict[tuple, int] = defaultdict(int)
    for v in db.scalars(q):
        s = stats.setdefault(v.competitor_id, PlayerStats(v.competitor_id))
        key = (v.game_id, v.leg_no, v.competitor_id)
        if leg_visits[key] == 0:
            s.legs += 1
        leg_visits[key] += 1
        leg_darts[key] += v.darts
        s.darts += v.darts
        s.points += v.score
        if leg_visits[key] <= 3:  # die ersten 9 Darts eines Legs
            s.first9_darts += v.darts
            s.first9_points += v.score
        if v.score == 180:
            s.max180 += 1
        elif v.score >= 140:
            s.ton40 += 1
        elif v.score >= 100:
            s.tons += 1
        if is_finishable(v.remaining_before):
            s.checkout_chances += 1
        if v.checkout:
            s.checkouts += 1
            s.legs_won += 1
            s.high_finish = max(s.high_finish, v.score)
            s.best_leg = leg_darts[key] if s.best_leg is None else min(s.best_leg, leg_darts[key])

    gq = select(models.DartsGame).where(models.DartsGame.status == "finished")
    if game_ids is not None:
        gq = gq.where(models.DartsGame.id.in_(game_ids))
    for g in db.scalars(gq):
        for p in g.players:
            if competitor_ids is not None and p.competitor_id not in competitor_ids:
                continue
            s = stats.setdefault(p.competitor_id, PlayerStats(p.competitor_id))
            s.games += 1
            if g.winner_id == p.competitor_id:
                s.wins += 1
    return stats


def leg_average(visits: list[models.DartsVisit], competitor_id: int, leg_no: int | None = None) -> float | None:
    """3-Dart-Average eines Spielers in einem Spiel (optional nur in einem Leg) - für die Anzeige im Spiel."""
    vs = [v for v in visits if v.competitor_id == competitor_id and (leg_no is None or v.leg_no == leg_no)]
    darts = sum(v.darts for v in vs)
    return 3 * sum(v.score for v in vs) / darts if darts else None
