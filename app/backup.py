"""Export (CSV für Excel) und Komplett-Backup/Wiederherstellung (JSON): Fantasy-Saison, Konten,
Einladungen sowie Darts, Beer Pong und Turniere."""

import base64
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
    avatars = dict(db.execute(select(models.Avatar.user_id, models.Avatar.image)).all())
    return {
        "version": BACKUP_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "season": {"key": season.key, "teams_locked": season.teams_locked,
                   "rules": get_setting(db, f"rules:{season.key}")},
        "users": [{"id": u.id, "username": u.username, "password_hash": u.password_hash, "is_admin": u.is_admin,
                   "avatar": base64.b64encode(avatars[u.id]).decode() if u.id in avatars else None}
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
        "invites": [{
            "token": i.token, "note": i.note, "used_by_id": i.used_by_id,
            "created_at": i.created_at.isoformat() if i.created_at else None,
            "used_at": i.used_at.isoformat() if i.used_at else None,
        } for i in db.scalars(select(models.Invite).order_by(models.Invite.id))],
        "platform": export_platform(db),
    }


def _iso(dt):
    return dt.isoformat() if dt else None


def export_platform(db: Session) -> dict:
    """Darts, Beer Pong und Turniere (saisonunabhängig)."""
    return {
        "competitors": [{"id": c.id, "name": c.name, "user_id": c.user_id}
                        for c in db.scalars(select(models.Competitor).order_by(models.Competitor.id)).unique()],
        "tournaments": [{
            "id": t.id, "sport": t.sport, "name": t.name, "status": t.status, "settings": t.settings,
            "winner_entry_id": t.winner_entry_id, "created_by_id": t.created_by_id,
            "created_at": _iso(t.created_at), "finished_at": _iso(t.finished_at),
            "entries": [{"id": e.id, "seed": e.seed, "name": e.name, "group_no": e.group_no,
                         "members": [m.competitor_id for m in e.members]} for e in t.entries],
            "matches": [{"id": m.id, "round": m.round, "slot": m.slot, "group_no": m.group_no,
                         "entry1_id": m.entry1_id, "entry2_id": m.entry2_id, "winner_id": m.winner_id,
                         "score1": m.score1, "score2": m.score2, "bye": m.bye, "updated_at": _iso(m.updated_at)}
                        for m in t.matches],
        } for t in db.scalars(select(models.Tournament).order_by(models.Tournament.id))],
        "darts_games": [{
            "start_score": g.start_score, "legs_to_win": g.legs_to_win, "status": g.status, "winner_id": g.winner_id,
            "team_size": g.team_size or 1, "winner_side": g.winner_side,
            "created_by_id": g.created_by_id, "created_at": _iso(g.created_at), "finished_at": _iso(g.finished_at),
            "tournament_match_id": g.tournament_match_id,
            "players": [[p.position, p.competitor_id] for p in g.players],
            "visits": [[v.seq, v.leg_no, v.position, v.competitor_id, v.score, v.darts, v.bust, v.checkout,
                        v.remaining_before] for v in g.visits],
        } for g in db.scalars(select(models.DartsGame).order_by(models.DartsGame.id))],
        "beerpong_games": [{
            "cups": g.cups, "hits1": g.hits1, "hits2": g.hits2, "status": g.status, "winner_side": g.winner_side,
            "version": g.version, "team1_name": g.team1_name, "team2_name": g.team2_name,
            "tournament_match_id": g.tournament_match_id, "created_by_id": g.created_by_id,
            "created_at": _iso(g.created_at), "finished_at": _iso(g.finished_at),
            "players": [[p.side, p.position, p.competitor_id] for p in g.players],
        } for g in db.scalars(select(models.BeerpongGame).order_by(models.BeerpongGame.id))],
    }


def restore_platform(db: Session, data: dict, user_map: dict[int, int]) -> bool:
    """Spieldaten einspielen - nur in eine DB ohne Spieldaten (sonst False, nichts passiert)."""
    if not data or db.scalar(select(models.DartsGame.id).limit(1)) or db.scalar(select(models.BeerpongGame.id).limit(1)) \
            or db.scalar(select(models.Tournament.id).limit(1)):
        return False

    def ts(value):
        return datetime.fromisoformat(value) if value else None

    def uid(old):
        return user_map.get(old) if old is not None else None

    cmap = {}
    for c in data.get("competitors", []):
        new_uid = uid(c["user_id"])
        obj = db.scalar(select(models.Competitor).where(models.Competitor.user_id == new_uid)) if new_uid else None
        if obj is None:
            obj = models.Competitor(name=c["name"], user_id=new_uid)
            db.add(obj)
            db.flush()
        cmap[c["id"]] = obj.id

    tm_map = {}
    for t in data.get("tournaments", []):
        nt = models.Tournament(sport=t["sport"], name=t["name"], status=t["status"], settings=t["settings"],
                               created_by_id=uid(t["created_by_id"]), created_at=ts(t["created_at"]),
                               finished_at=ts(t["finished_at"]))
        db.add(nt)
        db.flush()
        emap = {}
        for e in t["entries"]:
            ne = models.TournamentEntry(tournament_id=nt.id, seed=e["seed"], name=e["name"], group_no=e.get("group_no"),
                                        members=[models.TournamentEntryMember(position=i, competitor_id=cmap[cid])
                                                 for i, cid in enumerate(e["members"])])
            db.add(ne)
            db.flush()
            emap[e["id"]] = ne.id
        em = lambda x: emap.get(x) if x is not None else None  # noqa: E731
        nt.winner_entry_id = em(t["winner_entry_id"])
        for m in t["matches"]:
            nm = models.TournamentMatch(tournament_id=nt.id, round=m["round"], slot=m["slot"], group_no=m.get("group_no"),
                                        entry1_id=em(m["entry1_id"]), entry2_id=em(m["entry2_id"]),
                                        winner_id=em(m["winner_id"]), score1=m["score1"], score2=m["score2"],
                                        bye=m["bye"], updated_at=ts(m.get("updated_at")))
            db.add(nm)
            db.flush()
            tm_map[m["id"]] = nm.id
    tmid = lambda x: tm_map.get(x) if x is not None else None  # noqa: E731

    for g in data.get("darts_games", []):
        ng = models.DartsGame(start_score=g["start_score"], legs_to_win=g["legs_to_win"], status=g["status"],
                              team_size=g.get("team_size", 1), winner_side=g.get("winner_side"),
                              winner_id=cmap.get(g["winner_id"]), created_by_id=uid(g["created_by_id"]),
                              created_at=ts(g["created_at"]), finished_at=ts(g["finished_at"]),
                              tournament_match_id=tmid(g["tournament_match_id"]))
        ng.players = [models.DartsGamePlayer(position=pos, competitor_id=cmap[cid]) for pos, cid in g["players"]]
        db.add(ng)
        db.flush()
        for seq, leg, pos, cid, score, darts, bust, co, rem in g["visits"]:
            db.add(models.DartsVisit(game_id=ng.id, seq=seq, leg_no=leg, position=pos, competitor_id=cmap[cid],
                                     score=score, darts=darts, bust=bust, checkout=co, remaining_before=rem))
    for g in data.get("beerpong_games", []):
        ng = models.BeerpongGame(cups=g["cups"], hits1=g["hits1"], hits2=g["hits2"], status=g["status"],
                                 winner_side=g["winner_side"], version=g["version"], team1_name=g["team1_name"],
                                 team2_name=g["team2_name"], tournament_match_id=tmid(g["tournament_match_id"]),
                                 created_by_id=uid(g["created_by_id"]), created_at=ts(g["created_at"]),
                                 finished_at=ts(g["finished_at"]))
        ng.players = [models.BeerpongGamePlayer(side=side, position=pos, competitor_id=cmap[cid])
                      for side, pos, cid in g["players"]]
        db.add(ng)
    db.flush()
    return True


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
            if u.get("avatar"):  # ältere Backups haben keine Profilbilder
                db.add(models.Avatar(user_id=existing.id, image=base64.b64decode(u["avatar"])))
                existing.avatar_version = int(datetime.now(timezone.utc).timestamp())
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
    # Einladungslinks (ältere Backups haben keine). Schon vorhandene Tokens bleiben unverändert.
    known = set(db.scalars(select(models.Invite.token)))
    for i in data.get("invites", []):
        if i["token"] in known:
            continue
        db.add(models.Invite(
            token=i["token"], note=i["note"], used_by_id=user_map.get(i["used_by_id"]),
            created_at=ts(i["created_at"]) or datetime.now(timezone.utc), used_at=ts(i["used_at"]),
        ))
    restore_platform(db, data.get("platform"), user_map)  # ältere Backups haben keine Spieldaten
    db.commit()
    return season
