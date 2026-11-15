"""Zugriff auf die aktive Saison, Lock-Status und Import der Saison-Daten (CSV)."""

import csv
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import models
from .rules import Rules, load_rules, season_dir
from .settings import get_settings


class SeasonNotImported(Exception):
    pass


def get_season(db: Session, key: str | None = None) -> models.Season:
    key = key or get_settings().season
    season = db.scalar(select(models.Season).where(models.Season.key == key))
    if season is None:
        raise SeasonNotImported(key)
    return season


def is_locked(season: models.Season, rules: Rules, now: datetime | None = None) -> bool:
    if season.teams_locked:
        return True
    if rules.lock_at is not None:
        return (now or datetime.now(timezone.utc)) >= rules.lock_at
    return False


def season_players(db: Session, season: models.Season) -> dict[int, models.Player]:
    players = db.scalars(select(models.Player).where(models.Player.season_id == season.id)).all()
    return {p.id: p for p in players}


def season_matches(db: Session, season: models.Season) -> list[models.Match]:
    return list(
        db.scalars(
            select(models.Match)
            .where(models.Match.season_id == season.id)
            .order_by(models.Match.round, models.Match.slot)
        )
    )


# ---------------------------------------------------------------- Import


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def import_season(db: Session, key: str, replace: bool = False) -> models.Season:
    """Legt eine Saison aus seasons/<key>/{players.csv,draw.csv} an.

    players.csv: name,price,nation,seed
    draw.csv:    player1,player2   (Paarungen der 1. Runde in Turnierbaum-Reihenfolge)
    """
    rules = load_rules(key)
    folder = season_dir(key)
    player_rows = _read_csv(folder / "players.csv")
    draw_rows = _read_csv(folder / "draw.csv")

    # --- validieren, bevor irgendetwas geschrieben wird
    names = [r["name"].strip() for r in player_rows]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"Doppelte Spieler in players.csv: {sorted(dupes)}")
    expected = rules.matches_in_round(1)
    if len(draw_rows) != expected:
        raise ValueError(f"draw.csv hat {len(draw_rows)} Paarungen, für {rules.tournament.num_rounds} Runden braucht es {expected}")
    drawn = [r[c].strip() for r in draw_rows for c in ("player1", "player2")]
    unknown = sorted(set(drawn) - set(names))
    if unknown:
        raise ValueError(f"Spieler aus draw.csv fehlen in players.csv: {unknown}")
    if len(set(drawn)) != len(drawn):
        raise ValueError("Ein Spieler kommt in draw.csv mehrfach vor")

    season = db.scalar(select(models.Season).where(models.Season.key == key))
    if season is not None:
        if not replace:
            raise ValueError(f"Saison '{key}' existiert schon. Mit --replace komplett neu anlegen (löscht Teams & Ergebnisse!).")
        for model in (models.Team, models.Match, models.Player):
            db.execute(delete(model).where(model.season_id == season.id))
    else:
        season = models.Season(key=key)
        db.add(season)
        db.flush()

    by_name = {}
    for r in player_rows:
        seed = (r.get("seed") or "").strip()
        p = models.Player(
            season_id=season.id,
            name=r["name"].strip(),
            nation=(r.get("nation") or "").strip(),
            price=float(r["price"]),
            seed=int(seed) if seed and seed.lower() != "none" else None,
        )
        db.add(p)
        by_name[p.name] = p
    db.flush()

    for rnd in range(1, rules.tournament.num_rounds + 1):
        for slot in range(rules.matches_in_round(rnd)):
            m = models.Match(season_id=season.id, round=rnd, slot=slot, stats_p1={}, stats_p2={})
            if rnd == 1:
                row = draw_rows[slot]
                m.p1_id = by_name[row["player1"].strip()].id
                m.p2_id = by_name[row["player2"].strip()].id
            db.add(m)
    db.commit()
    return season
