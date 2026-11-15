"""Export (CSV für Excel) und Komplett-Backup/Wiederherstellung (JSON) einer Saison."""

import csv
import io
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .config_store import get_setting
from .rules import Rules
from .scoring import player_scores, team_score

BACKUP_VERSION = 1


# ---------------------------------------------------------------- CSV


def _csv(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    # Semikolon + BOM: öffnet sich in deutschem Excel direkt korrekt
    w = csv.writer(buf, delimiter=";")
    w.writerow(header)
    w.writerows(rows)
    return "﻿" + buf.getvalue()


def _season_data(db: Session, season: models.Season):
    players = {p.id: p for p in db.scalars(select(models.Player).where(models.Player.season_id == season.id))}
    matches = list(db.scalars(select(models.Match).where(models.Match.season_id == season.id)
                              .order_by(models.Match.round, models.Match.slot)))
    teams = list(db.scalars(select(models.Team).where(models.Team.season_id == season.id).order_by(models.Team.id)))
    return players, matches, teams


def teams_csv(db: Session, season: models.Season, rules: Rules) -> str:
    players, matches, teams = _season_data(db, season)
    scores = player_scores(rules, matches)
    name = lambda pid: players[pid].name if pid in players else ""  # noqa: E731
    rows = []
    for t in teams:
        squad = sorted(t.player_ids, key=lambda pid: -players[pid].price)
        rows.append([
            t.name, t.user.username, "yes" if t.is_active else "no",
            f"{team_score(rules, t, scores).total:g}",
            name(t.playmaker_id), name(t.underdog_id), name(t.champion_pick_id),
            f"{sum(players[pid].price for pid in squad):.1f}",
            ", ".join(name(pid) for pid in squad),
        ])
    return _csv(["team", "user", "active", "points", "playmaker", "underdog", "champion_pick", "spent", "players"], rows)


def results_csv(db: Session, season: models.Season, rules: Rules) -> str:
    players, matches, _ = _season_data(db, season)
    keys = [s.key for s in rules.scoring.stats]
    name = lambda pid: players[pid].name if pid in players else ""  # noqa: E731
    rows = []
    for m in matches:
        if not m.is_played:
            continue
        rows.append([
            rules.tournament.round_names[m.round - 1], m.slot + 1, name(m.p1_id), m.sets_p1, m.sets_p2, name(m.p2_id),
            name(m.winner_id),
            *[(m.stats_p1 or {}).get(k, 0) for k in keys], *[(m.stats_p2 or {}).get(k, 0) for k in keys],
        ])
    header = ["round", "match", "player1", "sets1", "sets2", "player2", "winner",
              *[f"p1_{k}" for k in keys], *[f"p2_{k}" for k in keys]]
    return _csv(header, rows)


def players_csv(db: Session, season: models.Season, rules: Rules) -> str:
    players, matches, teams = _season_data(db, season)
    scores = player_scores(rules, matches)
    active = [t for t in teams if t.is_active]
    rows = []
    for p in sorted(players.values(), key=lambda p: -(scores[p.id].points if p.id in scores else 0)):
        s = scores.get(p.id)
        picked = sum(1 for t in active if p.id in t.player_ids)
        rows.append([p.name, p.nation, p.seed or "", f"{p.price:.1f}", f"{s.points if s else 0:g}",
                     "out" if s and s.eliminated else ("champion" if s and s.is_champion else "in"), picked])
    return _csv(["player", "nation", "seed", "price", "points", "status", "picked_by_active_teams"], rows)


# ---------------------------------------------------------------- JSON-Backup


def export_backup(db: Session, season: models.Season) -> dict:
    """Alles, was nötig ist, um die Saison inkl. User in einer leeren DB wiederherzustellen.

    Enthält Passwort-Hashes (keine Klartext-Passwörter) - Datei vertraulich behandeln.
    """
    players, matches, teams = _season_data(db, season)
    users = db.scalars(select(models.User).order_by(models.User.id)).all()
    return {
        "version": BACKUP_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "season": {"key": season.key, "teams_locked": season.teams_locked,
                   "rules": get_setting(db, f"rules:{season.key}")},
        "users": [{"id": u.id, "username": u.username, "password_hash": u.password_hash, "is_admin": u.is_admin}
                  for u in users],
        "players": [{"id": p.id, "name": p.name, "nation": p.nation, "price": p.price, "seed": p.seed}
                    for p in players.values()],
        "matches": [{
            "round": m.round, "slot": m.slot, "p1_id": m.p1_id, "p2_id": m.p2_id, "winner_id": m.winner_id,
            "sets_p1": m.sets_p1, "sets_p2": m.sets_p2, "stats_p1": m.stats_p1 or {}, "stats_p2": m.stats_p2 or {},
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
        } for m in matches],
        "teams": [{
            "name": t.name, "user_id": t.user_id, "is_active": t.is_active, "player_ids": t.player_ids,
            "playmaker_id": t.playmaker_id, "underdog_id": t.underdog_id, "champion_pick_id": t.champion_pick_id,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        } for t in teams],
    }


def restore_backup(db: Session, data: dict) -> models.Season:
    """Spielt ein Backup ein. Die Saison darf noch nicht existieren; User werden per Name zusammengeführt."""
    if data.get("version") != BACKUP_VERSION:
        raise ValueError(f"Unbekannte Backup-Version: {data.get('version')}")
    key = data["season"]["key"]
    if db.scalar(select(models.Season).where(models.Season.key == key)) is not None:
        raise ValueError(f"Saison '{key}' existiert schon in dieser Datenbank - Backup nur in eine DB ohne diese Saison einspielen.")

    def ts(value):
        return datetime.fromisoformat(value) if value else None

    user_map = {}
    for u in data["users"]:
        existing = db.scalar(select(models.User).where(models.User.username == u["username"]))
        if existing is None:
            existing = models.User(username=u["username"], password_hash=u["password_hash"], is_admin=u["is_admin"])
            db.add(existing)
            db.flush()
        user_map[u["id"]] = existing.id

    season = models.Season(key=key, teams_locked=data["season"]["teams_locked"])
    db.add(season)
    db.flush()
    if data["season"].get("rules"):
        db.add(models.AppSetting(key=f"rules:{key}", value=data["season"]["rules"]))

    player_map = {}
    for p in data["players"]:
        obj = models.Player(season_id=season.id, name=p["name"], nation=p["nation"], price=p["price"], seed=p["seed"])
        db.add(obj)
        db.flush()
        player_map[p["id"]] = obj.id
    pm = lambda pid: player_map.get(pid) if pid is not None else None  # noqa: E731

    for m in data["matches"]:
        db.add(models.Match(
            season_id=season.id, round=m["round"], slot=m["slot"], p1_id=pm(m["p1_id"]), p2_id=pm(m["p2_id"]),
            winner_id=pm(m["winner_id"]), sets_p1=m["sets_p1"], sets_p2=m["sets_p2"],
            stats_p1=m["stats_p1"], stats_p2=m["stats_p2"], updated_at=ts(m["updated_at"]),
            scheduled_at=ts(m.get("scheduled_at")),
        ))
    for t in data["teams"]:
        team = models.Team(
            season_id=season.id, user_id=user_map[t["user_id"]], name=t["name"], is_active=t["is_active"],
            playmaker_id=pm(t["playmaker_id"]), underdog_id=pm(t["underdog_id"]),
            champion_pick_id=pm(t["champion_pick_id"]), created_at=ts(t["created_at"]) or datetime.now(timezone.utc),
        )
        team.members = [models.TeamPlayer(player_id=pm(pid)) for pid in t["player_ids"]]
        db.add(team)
    db.commit()
    return season
