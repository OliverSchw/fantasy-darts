"""Darts-Erfolge (Abzeichen) - beim Durchgehen aller Spiele in zeitlicher Reihenfolge ermittelt, mit dem
Zeitpunkt, an dem sie zum ersten Mal erreicht wurden (für die Neuigkeiten). Nichts wird gespeichert.

Abgebrochene Spiele zählen nicht. Wurf-Erfolge (180, Finish ...) zählen auch in laufenden Spielen,
Spiel-Erfolge (Siege, Average im Spiel ...) erst, wenn das Spiel beendet ist.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..confirmations import pending_pairs, pending_tournament_pairs
from .modes import TRAINING, parse_dart
from .rating import aware, cached

# Schlüssel: (Symbol, Name, Beschreibung)
ACHIEVEMENTS = {
    "first_win": ("🥇", "First win", "Win a game"),
    "ton": ("💯", "Ton", "Score 100+ in one visit"),
    "ton80": ("🔥", "Maximum", "Throw a 180"),
    "club180": ("🎰", "180 Club", "Throw ten 180s"),
    "ton_out": ("🧨", "Ton-up finish", "Check out 100 or more"),
    "big_fish": ("🐟", "Big Fish", "Check out 170"),
    "bull_finish": ("🐂", "Bullseye finish", "Win a leg on the bull"),
    "short_leg": ("⚡", "Short leg", "Win a leg in 15 darts or fewer (singles)"),
    "twelve": ("🚀", "Twelve-darter", "Win a leg in 12 darts or fewer (singles)"),
    "avg60": ("📈", "Sixty club", "Average 60+ in a finished X01 game"),
    "avg80": ("🌟", "Eighty club", "Average 80+ in a finished X01 game"),
    "regular": ("🗓️", "Regular", "Play 25 games"),
    "wins10": ("🏅", "Ten wins", "Win 10 games"),
    "party": ("🎉", "Party animal", "Win Cricket, Around the Clock, Shanghai and Killer"),
    "shanghai": ("🀄", "Shanghai!", "Win Shanghai with single, double and treble of the number"),
    "champion": ("🏆", "Champion", "Win a darts tournament"),
}
PARTY_MODES = {"cricket", "atc", "shanghai", "killer"}


@dataclass
class Earned:
    key: str
    competitor_id: int
    at: datetime
    game_id: int | None = None
    tournament_id: int | None = None

    @property
    def icon(self) -> str:
        return ACHIEVEMENTS[self.key][0]

    @property
    def name(self) -> str:
        return ACHIEVEMENTS[self.key][1]

    @property
    def description(self) -> str:
        return ACHIEVEMENTS[self.key][2]


def _is_shanghai(throws: list[str] | None) -> bool:
    if not throws or len(throws) != 3:
        return False
    darts = [parse_dart(t) for t in throws]
    return {m for m, _ in darts} == {1, 2, 3} and len({n for _, n in darts}) == 1


def compute_achievements(db: Session) -> dict[int, list[Earned]]:
    """{competitor_id: [Earned, ...]} in der Reihenfolge, in der sie erreicht wurden."""
    return cached(db, "achievements", lambda: _compute(db))


def _compute(db: Session) -> dict[int, list[Earned]]:
    out: dict[int, dict[str, Earned]] = {}

    pend = pending_pairs(db)
    pend_t = pending_tournament_pairs(db)

    def earn(cid, key, at, game_id=None, tournament_id=None):
        if (game_id is not None and (game_id, cid) in pend) or (tournament_id is not None and (tournament_id, cid) in pend_t):
            return  # noch nicht bestätigt
        got = out.setdefault(cid, {})
        if key not in got:
            got[key] = Earned(key, cid, at, game_id, tournament_id)

    games = db.scalars(select(models.DartsGame).where(models.DartsGame.status != "abandoned")).all()
    games = sorted(games, key=lambda g: (aware(g.finished_at or g.created_at), g.id))
    played: dict[int, int] = {}
    wins: dict[int, int] = {}
    max180: dict[int, int] = {}
    party_wins: dict[int, set] = {}
    for g in games:
        at = aware(g.finished_at or g.created_at)
        if g.mode == "x01":
            leg_darts: dict[tuple, int] = {}
            for v in g.visits:
                v_at = aware(v.created_at or at)
                key = (v.leg_no, v.competitor_id)
                leg_darts[key] = leg_darts.get(key, 0) + v.darts
                if v.score >= 100:
                    earn(v.competitor_id, "ton", v_at, g.id)
                if v.score == 180:
                    earn(v.competitor_id, "ton80", v_at, g.id)
                    if (g.id, v.competitor_id) not in pend:
                        max180[v.competitor_id] = max180.get(v.competitor_id, 0) + 1
                    if max180.get(v.competitor_id) == 10:
                        earn(v.competitor_id, "club180", v_at, g.id)
                if v.checkout:
                    if v.score >= 100:
                        earn(v.competitor_id, "ton_out", v_at, g.id)
                    if v.score == 170:
                        earn(v.competitor_id, "big_fish", v_at, g.id)
                    if (v.throws and v.throws[-1] == "DB") or (not v.throws and v.score == 50 and v.darts == 1):
                        earn(v.competitor_id, "bull_finish", v_at, g.id)
                    if (g.team_size or 1) == 1:
                        if leg_darts[key] <= 15:
                            earn(v.competitor_id, "short_leg", v_at, g.id)
                        if leg_darts[key] <= 12:
                            earn(v.competitor_id, "twelve", v_at, g.id)
        if g.status != "finished":
            continue
        winners = ({p.competitor_id for p in g.players if g.won_by(p.competitor_id)}
                   if g.n_sides > 1 and g.mode not in TRAINING and not g.has_bot else set())
        for p in g.players:
            cid = p.competitor_id
            if (g.id, cid) in pend:
                continue
            played[cid] = played.get(cid, 0) + 1
            if played[cid] == 25:
                earn(cid, "regular", at, g.id)
            if g.mode == "x01":
                vs = [v for v in g.visits if v.competitor_id == cid]
                darts = sum(v.darts for v in vs)
                avg = 3 * sum(v.score for v in vs) / darts if darts else 0
                if avg >= 60:
                    earn(cid, "avg60", at, g.id)
                if avg >= 80:
                    earn(cid, "avg80", at, g.id)
            if cid in winners:
                wins[cid] = wins.get(cid, 0) + 1
                earn(cid, "first_win", at, g.id)
                if wins[cid] == 10:
                    earn(cid, "wins10", at, g.id)
                if g.mode in PARTY_MODES:
                    party_wins.setdefault(cid, set()).add(g.mode)
                    if party_wins[cid] == PARTY_MODES:
                        earn(cid, "party", at, g.id)
                if g.mode == "shanghai" and g.visits and _is_shanghai(g.visits[-1].throws):
                    earn(cid, "shanghai", at, g.id)

    for t in db.scalars(select(models.Tournament).where(models.Tournament.sport == "darts",
                                                        models.Tournament.winner_entry_id.is_not(None))):
        entry = next((e for e in t.entries if e.id == t.winner_entry_id), None)
        at = aware(t.finished_at or t.created_at)
        for c in entry.competitors if entry else []:
            earn(c.id, "champion", at, tournament_id=t.id)

    bots = set(db.scalars(select(models.Competitor.id).where(models.Competitor.bot_level.is_not(None))))
    return {cid: sorted(got.values(), key=lambda e: e.at) for cid, got in out.items() if cid not in bots}
