"""Team-Validierung (alle Regeln aus rules.toml) und Speichern."""

from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import models
from .rules import Rules


@dataclass
class TeamInput:
    name: str
    player_ids: list[int]
    playmaker_id: int | None
    underdog_id: int | None
    champion_pick_id: int | None


def validate_team(rules: Rules, data: TeamInput, players: dict[int, models.Player]) -> list[str]:
    """Gibt eine Liste von Fehlermeldungen zurück (leer = alles ok)."""
    tr = rules.team
    errors = []
    name = data.name.strip()
    if not name:
        errors.append("Please give your team a name.")
    elif len(name) > 40:
        errors.append("Team name must be at most 40 characters.")

    ids = data.player_ids
    if len(set(ids)) != len(ids):
        errors.append("A player was selected twice.")
    unknown = [i for i in ids if i not in players]
    if unknown:
        errors.append("Unknown player selected.")
    if len(set(ids)) != tr.squad_size:
        errors.append(f"Select exactly {tr.squad_size} players (currently {len(set(ids))}).")

    total = sum(players[i].price for i in set(ids) if i in players)
    if total > tr.budget + 1e-6:
        errors.append(f"Budget exceeded: {total:.1f} of {tr.budget:.1f}.")

    for role, pid in ((tr.playmaker, data.playmaker_id), (tr.underdog, data.underdog_id)):
        if pid is None:
            errors.append(f"Choose a {role.label}.")
        elif pid not in ids:
            errors.append(f"The {role.label} must be part of your team.")
        elif players[pid].price > role.max_price + 1e-6:
            errors.append(f"The {role.label} may cost at most {role.max_price:.1f}.")

    if data.champion_pick_id is None or data.champion_pick_id not in players:
        errors.append("Choose a champion pick.")
    return errors


def name_taken(db: Session, season_id: int, name: str, exclude_team_id: int | None = None) -> bool:
    q = select(models.Team.id).where(
        models.Team.season_id == season_id, func.lower(models.Team.name) == name.strip().lower()
    )
    if exclude_team_id is not None:
        q = q.where(models.Team.id != exclude_team_id)
    return db.scalar(q) is not None


def user_teams(db: Session, season_id: int, user_id: int) -> list[models.Team]:
    return list(
        db.scalars(
            select(models.Team)
            .where(models.Team.season_id == season_id, models.Team.user_id == user_id)
            .order_by(models.Team.created_at)
        )
    )


def save_team(db: Session, team: models.Team, data: TeamInput) -> models.Team:
    team.name = data.name.strip()
    team.playmaker_id = data.playmaker_id
    team.underdog_id = data.underdog_id
    team.champion_pick_id = data.champion_pick_id
    existing = {m.player_id: m for m in team.members}
    team.members = [existing.get(pid) or models.TeamPlayer(player_id=pid) for pid in dict.fromkeys(data.player_ids)]
    db.add(team)
    db.flush()
    # Erstes Team eines Users wird automatisch aktiv.
    has_active = db.scalar(
        select(models.Team.id).where(
            models.Team.season_id == team.season_id,
            models.Team.user_id == team.user_id,
            models.Team.is_active.is_(True),
        )
    )
    if has_active is None:
        team.is_active = True
    db.commit()
    return team


def activate_team(db: Session, team: models.Team) -> None:
    db.execute(
        update(models.Team)
        .where(models.Team.season_id == team.season_id, models.Team.user_id == team.user_id)
        .values(is_active=False)
    )
    db.flush()
    team.is_active = True
    db.commit()


def delete_team(db: Session, team: models.Team) -> None:
    was_active = team.is_active
    season_id, user_id = team.season_id, team.user_id
    db.delete(team)
    db.flush()
    if was_active:  # anderes Team nachrücken lassen
        other = db.scalar(
            select(models.Team)
            .where(models.Team.season_id == season_id, models.Team.user_id == user_id)
            .order_by(models.Team.created_at)
        )
        if other is not None:
            other.is_active = True
    db.commit()
