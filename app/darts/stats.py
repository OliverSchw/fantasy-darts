"""Darts-Statistik pro Teilnehmer - immer frisch aus den Aufnahmen berechnet (nichts gespeichert).

Average, Checkout & Co. kommen nur aus X01-Spielen; die Partyspiele haben eigene Bilanzen (mode_records).

Abgebrochene Spiele zählen nicht. Laufende Spiele zählen bei Würfen mit, aber nicht bei Siegen.
"""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from .checkouts import is_finishable
from .modes import TRAINING, replay_mode
from .throws import double_attempts


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
    double_darts: int = 0  # nur aus Aufnahmen, die Dart für Dart eingegeben wurden
    double_hits: int = 0

    @property
    def double_pct(self) -> float | None:
        return 100 * self.double_hits / self.double_darts if self.double_darts else None

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
         .where(models.DartsGame.status != "abandoned", models.DartsGame.mode == "x01")
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
        if v.throws:
            tries, hits = double_attempts(v.remaining_before, v.throws)
            s.double_darts += tries
            s.double_hits += hits
        if v.checkout:
            s.checkouts += 1
            s.legs_won += 1
            s.high_finish = max(s.high_finish, v.score)
            s.best_leg = leg_darts[key] if s.best_leg is None else min(s.best_leg, leg_darts[key])

    gq = select(models.DartsGame).where(models.DartsGame.status == "finished", models.DartsGame.mode == "x01")
    if game_ids is not None:
        gq = gq.where(models.DartsGame.id.in_(game_ids))
    for g in db.scalars(gq):
        if g.has_bot:
            continue  # gegen Bots: Würfe zählen, Siege nicht (Training)
        for p in g.players:
            if competitor_ids is not None and p.competitor_id not in competitor_ids:
                continue
            s = stats.setdefault(p.competitor_id, PlayerStats(p.competitor_id))
            s.games += 1
            if g.won_by(p.competitor_id):
                s.wins += 1
    return stats


def leg_average(visits: list[models.DartsVisit], competitor_id: int, leg_no: int | None = None) -> float | None:
    """3-Dart-Average eines Spielers in einem Spiel (optional nur in einem Leg) - für die Anzeige im Spiel."""
    vs = [v for v in visits if v.competitor_id == competitor_id and (leg_no is None or v.leg_no == leg_no)]
    darts = sum(v.darts for v in vs)
    return 3 * sum(v.score for v in vs) / darts if darts else None


# ---------------------------------------------------------------- Vergleich zweier Spieler

# (Schlüssel, Bezeichnung, höher ist besser?, Format)
COMPARE_ROWS = (
    ("average", "3-dart average", True, "avg"),
    ("first9", "First 9 average", True, "avg"),
    ("win_pct", "Win rate", True, "pct"),
    ("games", "Games played", None, "int"),
    ("legs_won", "Legs won", True, "int"),
    ("max180", "180s", True, "int"),
    ("ton40", "140+", True, "int"),
    ("tons", "100+", True, "int"),
    ("high_finish", "Highest finish", True, "int"),
    ("best_leg", "Best leg (darts)", False, "int"),
    ("checkout_pct", "Checkout rate", True, "pct"),
    ("double_pct", "Doubles hit", True, "pct"),
)


def compare_rows(a: PlayerStats | None, b: PlayerStats | None) -> list[dict]:
    """Zeilen für die Vergleichstabelle; winner = "a", "b" oder None (gleich / nicht vergleichbar)."""
    rows = []
    for key, label, higher, fmt in COMPARE_ROWS:
        va = getattr(a, key) if a else None
        vb = getattr(b, key) if b else None
        if key == "high_finish":
            va, vb = va or None, vb or None
        winner = None
        if higher is not None and va is not None and vb is not None and va != vb:
            winner = "a" if (va > vb) == higher else "b"
        elif key in ("high_finish", "best_leg") and (va is None) != (vb is None) and a and b:
            winner = "a" if va is not None else "b"  # ein Finish / gewonnenes Leg schlägt keins
        rows.append({"label": label, "a": va, "b": vb, "fmt": fmt, "winner": winner})
    return rows


@dataclass
class HeadToHead:
    game_ids: list[int]
    wins_a: int = 0
    wins_b: int = 0
    legs_a: int = 0
    legs_b: int = 0
    stats_a: PlayerStats | None = None  # nur aus den gemeinsamen Spielen
    stats_b: PlayerStats | None = None


def head_to_head(db: Session, a: int, b: int) -> HeadToHead:
    """Alle (nicht abgebrochenen) Spiele, in denen a und b gegeneinander gespielt haben."""
    pa = select(models.DartsGamePlayer.game_id).where(models.DartsGamePlayer.competitor_id == a)
    pb = select(models.DartsGamePlayer.game_id).where(models.DartsGamePlayer.competitor_id == b)
    games = db.scalars(select(models.DartsGame).where(
        models.DartsGame.id.in_(pa), models.DartsGame.id.in_(pb), models.DartsGame.status != "abandoned",
        models.DartsGame.mode == "x01")
        .order_by(models.DartsGame.created_at.desc(), models.DartsGame.id.desc())).all()
    # nur Spiele, in denen a und b auf verschiedenen Seiten standen (im Doppel nicht als Partner)
    def side(g, cid):
        return next(g.side_of(p.position) for p in g.players if p.competitor_id == cid)
    games = [g for g in games if side(g, a) != side(g, b)]
    h = HeadToHead(game_ids=[g.id for g in games])
    for g in games:
        if g.status == "finished":
            h.wins_a += g.won_by(a)
            h.wins_b += g.won_by(b)
        for v in g.visits:
            if v.checkout:
                h.legs_a += v.competitor_id == a
                h.legs_b += v.competitor_id == b
    if h.game_ids:
        s = compute_stats(db, [a, b], game_ids=h.game_ids)
        h.stats_a, h.stats_b = s.get(a), s.get(b)
    return h


def mode_records(db: Session, competitor_ids: list[int]) -> dict[int, dict[str, tuple[int, int]]]:
    """Siege/Spiele pro Partyspiel-Modus: {competitor_id: {"cricket": (wins, games), ...}} (nur beendete Spiele)."""
    out: dict[int, dict[str, list[int]]] = {}
    games = db.scalars(select(models.DartsGame).where(models.DartsGame.status == "finished",
                                                      models.DartsGame.mode.not_in(["x01", *TRAINING])))
    for g in games:
        for p in g.players:
            if p.competitor_id not in competitor_ids:
                continue
            rec = out.setdefault(p.competitor_id, {}).setdefault(g.mode, [0, 0])
            rec[1] += 1
            rec[0] += g.won_by(p.competitor_id)
    return {cid: {m: (w, n) for m, (w, n) in recs.items()} for cid, recs in out.items()}


# ---------------------------------------------------------------- Training (Bob's 27, 121 Checkout)


def training_records(db: Session, competitor_id: int) -> dict[str, dict]:
    """Bestwerte pro Trainingsmodus aus beendeten Spielen:
    bobs27 -> {"games", "best", "avg"}, checkout121 -> {"games", "best_hits", "attempts", "hits", "highest"}."""
    out: dict[str, dict] = {}
    game_ids = select(models.DartsGamePlayer.game_id).where(models.DartsGamePlayer.competitor_id == competitor_id)
    games = db.scalars(select(models.DartsGame).where(models.DartsGame.id.in_(game_ids),
                                                      models.DartsGame.status == "finished",
                                                      models.DartsGame.mode.in_(TRAINING)))
    for g in games:
        pos = next(p.position for p in g.players if p.competitor_id == competitor_id)
        s = replay_mode(g.mode, len(g.players), g.options or {}, [v.throws or [] for v in g.visits])
        r = out.setdefault(g.mode, {"games": 0})
        r["games"] += 1
        if g.mode == "bobs27":
            r["best"] = max(r.get("best", s.points[pos]), s.points[pos])
            r["total"] = r.get("total", 0) + s.points[pos]
            r["avg"] = r["total"] / r["games"]
        else:
            r["best_hits"] = max(r.get("best_hits", 0), s.successes[pos])
            r["hits"] = r.get("hits", 0) + s.successes[pos]
            r["attempts"] = r.get("attempts", 0) + s.attempts[pos]
            r["highest"] = max(r.get("highest", 0), s.best[pos])
    return out


def player_profile(db: Session, competitor_id: int, last: int | None = None) -> dict | None:
    """Average und Doppelquote eines Spielers (alle oder die letzten `last` beendeten X01-Spiele) - Vorlage für
    einen Bot. Ohne Dart-für-Dart-Daten wird die Doppelquote aus dem Average geschätzt."""
    from .bot import estimated_double_pct
    game_ids = select(models.DartsGamePlayer.game_id).where(models.DartsGamePlayer.competitor_id == competitor_id)
    games = db.scalars(select(models.DartsGame.id).where(
        models.DartsGame.id.in_(game_ids), models.DartsGame.status == "finished", models.DartsGame.mode == "x01")
        .order_by(models.DartsGame.finished_at.desc(), models.DartsGame.id.desc()).limit(last)).all()
    if not games:
        return None
    s = compute_stats(db, [competitor_id], game_ids=list(games)).get(competitor_id)
    if s is None or s.average is None:
        return None
    measured = s.double_pct is not None and s.double_darts >= 10
    return {"average": s.average, "double": s.double_pct if measured else estimated_double_pct(s.average),
            "estimated": not measured, "games": len(games)}


def bot_records(db: Session, competitor_id: int) -> list[tuple[models.Competitor, int, int]]:
    """Bilanz gegen Bots: [(Bot, Siege, Spiele), ...] aus beendeten Spielen, stärkste Stufe zuletzt."""
    out: dict[int, list] = {}
    game_ids = select(models.DartsGamePlayer.game_id).where(models.DartsGamePlayer.competitor_id == competitor_id)
    for g in db.scalars(select(models.DartsGame).where(models.DartsGame.id.in_(game_ids),
                                                       models.DartsGame.status == "finished")):
        me = next(p for p in g.players if p.competitor_id == competitor_id)
        bots = {p.competitor.id: p.competitor for p in g.players
                if p.competitor.is_bot and g.side_of(p.position) != g.side_of(me.position)}
        for bid, bot in bots.items():
            rec = out.setdefault(bid, [bot, 0, 0])
            rec[2] += 1
            rec[1] += g.won_by(competitor_id)
    order = {"easy": 0, "medium": 1, "hard": 2, "pro": 3}
    return sorted((tuple(r) for r in out.values()), key=lambda r: (order.get(r[0].bot_level, 4), r[0].name))
