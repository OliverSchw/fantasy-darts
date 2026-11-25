"""Neuigkeiten (Startseite und Darts): was zuletzt passiert ist - aus den vorhandenen Daten zusammengestellt.

Turniersieger (Darts und Beer Pong), beendete Spiele (mit Elo-Änderung), 180er, Finishes ab 100
und neu erreichte Erfolge. Nichts wird extra gespeichert.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .darts.achievements import compute_achievements
from .darts.modes import TRAINING
from .darts.rating import aware, compute_elo

DAYS = 30


@dataclass
class Item:
    at: datetime
    icon: str
    text: str
    url: str | None = None
    sport: str = "darts"
    result: bool = False  # einfaches Spielergebnis (auf der Darts-Seite stehen die ohnehin unter "Recent games")


def _since() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=DAYS)


def _game_title(g: models.DartsGame) -> str:
    from .darts.modes import MODES
    return MODES[g.mode]["name"] if g.mode != "x01" else str(g.start_score)


def darts_items(db: Session, since: datetime) -> list[Item]:
    items: list[Item] = []
    elo = compute_elo(db)
    games = db.scalars(select(models.DartsGame).where(models.DartsGame.status == "finished",
                                                      models.DartsGame.finished_at >= since)).all()
    for g in games:
        at = aware(g.finished_at or g.created_at)
        if at < since or g.n_sides < 2 or g.winning_side is None or g.mode in TRAINING or g.has_bot:
            continue
        win = g.winning_side
        losers = [g.side_name(s) for s in range(g.n_sides) if s != win]
        score = ""
        if g.mode == "x01" and g.n_sides == 2:
            legs = [sum(1 for v in g.visits if v.checkout and g.side_of(v.position) == s) for s in range(2)]
            score = f" {legs[win]}:{legs[1 - win]}"
        delta = elo.deltas.get(g.id, {}).get(g.side_players(win)[0].competitor_id)
        extra = f" · +{delta:.0f} Elo" if delta and round(delta) > 0 else ""
        items.append(Item(at, "🎯", f"{g.side_name(win)} beat {' & '.join(losers) if len(losers) < 3 else 'everyone'}"
                                    f"{score} ({_game_title(g)}){extra}", f"/darts/games/{g.id}", result=True))
    # Würfe: 180er und hohe Finishes (auch aus laufenden Spielen)
    q = (select(models.DartsVisit, models.DartsGame)
         .join(models.DartsGame, models.DartsGame.id == models.DartsVisit.game_id)
         .where(models.DartsGame.status != "abandoned", models.DartsGame.mode == "x01",
                (models.DartsVisit.score == 180) | (models.DartsVisit.checkout & (models.DartsVisit.score >= 100))))
    names: dict[int, str] = {}
    for v, g in db.execute(q):
        at = aware(v.created_at)
        if at < since:
            continue
        who = next(p.competitor for p in g.players if p.competitor_id == v.competitor_id)
        if who.is_bot:
            continue  # die Würfe der Bots sind keine Neuigkeit
        name = names.get(v.competitor_id) or who.display_name
        names[v.competitor_id] = name
        if v.checkout:
            items.append(Item(at, "🧨", f"{name} checked out {v.score}", f"/darts/games/{g.id}"))
        else:
            items.append(Item(at, "🔥", f"{name} threw a 180", f"/darts/games/{g.id}"))
    # neue Erfolge (ohne die, die schon als Wurf oben stehen)
    shown = {"ton80", "ton_out", "champion"}
    people = {c.id: c for c in db.scalars(select(models.Competitor))}
    for cid, earned in compute_achievements(db).items():
        for e in earned:
            if e.at >= since and e.key not in shown and cid in people:
                items.append(Item(e.at, e.icon, f"{people[cid].display_name} unlocked “{e.name}”",
                                  f"/darts/players/{cid}"))
    return items


def tournament_items(db: Session, since: datetime) -> list[Item]:
    items = []
    for t in db.scalars(select(models.Tournament).where(models.Tournament.winner_entry_id.is_not(None))):
        at = aware(t.finished_at or t.created_at)
        entry = next((e for e in t.entries if e.id == t.winner_entry_id), None)
        if at < since or entry is None:
            continue
        base = "/beerpong" if t.sport == "beerpong" else "/darts"
        items.append(Item(at, "🏆", f"{entry.display_name} won {t.name}", f"{base}/tournaments/{t.id}", t.sport))
    return items


def beerpong_items(db: Session, since: datetime) -> list[Item]:
    items = []
    for g in db.scalars(select(models.BeerpongGame).where(models.BeerpongGame.status == "finished",
                                                          models.BeerpongGame.winner_side.is_not(None))):
        at = aware(g.finished_at or g.created_at)
        if at < since:
            continue
        w = g.winner_side
        hits = (g.hits1, g.hits2) if w == 1 else (g.hits2, g.hits1)
        items.append(Item(at, "🍺", f"{g.team_name(w)} beat {g.team_name(3 - w)} {hits[0]}:{hits[1]}",
                          f"/beerpong/games/{g.id}", "beerpong", result=True))
    return items


def news(db: Session, sport: str | None = None, limit: int = 12, results: bool = True) -> list[Item]:
    """Die neuesten Ereignisse (sport = "darts" / "beerpong" / None für alles; results=False ohne Spielergebnisse)."""
    since = _since()
    items = tournament_items(db, since)
    if sport in (None, "darts"):
        items += darts_items(db, since)
    if sport in (None, "beerpong"):
        items += beerpong_items(db, since)
    items = [i for i in items if (not sport or i.sport == sport) and (results or not i.result)]
    return sorted(items, key=lambda i: i.at, reverse=True)[:limit]
