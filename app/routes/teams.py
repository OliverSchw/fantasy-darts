from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from .. import database, models
from ..schemas import TeamCreate
from pydantic import BaseModel

router = APIRouter(prefix="/teams", tags=["teams"])


def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(db: Session = Depends(get_db)):
    # ... Implementierung der Benutzer-Authentifizierung ...
    # Nehmen wir an, wir geben hier den User mit ID 1 zurück
    user = db.get(models.User, 1)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# @router.post("/")
# def create_team(team: TeamCreate, db: Session = Depends(get_db)):
#     new_team = models.Team(name=team.team_name, user_id=team.user_id)
#     db.add(new_team)
#     db.commit()
#     db.refresh(new_team)

#     for pid in team.player_ids:
#         db.add(models.TeamPlayer(team_id=new_team.id, player_id=pid))
#     db.commit()

#     return {"team_id": new_team.id, "team_name": new_team.name}


# @router.post("/")
# def create_team(team: TeamCreate, db: Session = Depends(get_db)):
#     if (
#         team.captain_id not in team.player_ids
#         or team.underdog_id not in team.player_ids
#     ):
#         raise HTTPException(
#             status_code=400,
#             detail="Captain and Underdog must be in the selected player list.",
#         )

#     underdog_player = (
#         db.query(models.Player).filter(models.Player.id == team.underdog_id).first()
#     )
#     if not underdog_player or underdog_player.price >= 800.0:
#         raise HTTPException(
#             status_code=400, detail="Underdog must have a price less than 800.0."
#         )

#     new_team = models.Team(name=team.team_name, user_id=team.user_id)
#     db.add(new_team)
#     db.commit()
#     db.refresh(new_team)

#     for pid in team.player_ids:
#         # Setze is_captain/is_underdog basierend auf den übergebenen IDs
#         is_captain = pid == team.captain_id
#         is_underdog = pid == team.underdog_id

#         db.add(
#             models.TeamPlayer(
#                 team_id=new_team.id,
#                 player_id=pid,
#                 is_captain=is_captain,  # NEU
#                 is_underdog=is_underdog,  # NEU
#             )
#         )
#     db.commit()

#     return {"team_id": new_team.id, "team_name": new_team.name}


@router.post("/")
def create_team(team: TeamCreate, db: Session = Depends(get_db)):

    if (
        team.captain_id not in team.player_ids
        or team.underdog_id not in team.player_ids
    ):
        raise HTTPException(
            status_code=400,
            detail="Captain and Underdog must be in the selected player list.",
        )

    # 1.4 Champion Tipp muss existieren
    champion_player = (
        db.query(models.Player).filter(models.Player.id == team.champion_id).first()
    )
    if not champion_player:
        raise HTTPException(status_code=404, detail="Champion Pick player not found.")

    # --- Team-Erstellung ---
    new_team = models.Team(
        name=team.team_name,
        user_id=team.user_id,
        champion_id=team.champion_id,
    )
    db.add(new_team)
    db.commit()
    db.refresh(new_team)

    for pid in team.player_ids:
        is_captain = pid == team.captain_id
        is_underdog = pid == team.underdog_id

        db.add(
            models.TeamPlayer(
                team_id=new_team.id,
                player_id=pid,
                is_captain=is_captain,
                is_underdog=is_underdog,
            )
        )
    db.commit()

    return {"team_id": new_team.id, "team_name": new_team.name}


@router.put("/{team_id}")
def update_team(team_id: int, payload: dict, db: Session = Depends(get_db)):
    # 1. Team suchen
    team = db.query(models.Team).filter(models.Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # --- Daten aus Payload holen ---
    new_player_ids = payload.get("player_ids")
    new_captain_id = payload.get("captain_id")
    new_underdog_id = payload.get("underdog_id")
    new_champion_id = payload.get("champion_id")

    # Grundlegende Prüfung der Vollständigkeit
    if not all([new_player_ids, new_captain_id, new_underdog_id, new_champion_id]):
        raise HTTPException(
            status_code=400,
            detail="Missing required fields (player_ids, captain_id, underdog_id, champion_id).",
        )

    # --- Validierung der Geschäftsregeln ---

    # 2. Spieler-Objekte abrufen für Preisprüfung (nur die 15 Hauptspieler)
    all_players_in_team = (
        db.query(models.Player).filter(models.Player.id.in_(new_player_ids)).all()
    )
    player_map = {p.id: p for p in all_players_in_team}

    # 2.1 Teamgröße prüfen (wenn das Frontend dies nicht garantiert)
    if len(new_player_ids) != 15:
        raise HTTPException(
            status_code=400, detail="Team must contain exactly 15 players."
        )

    # 2.2 Captain und Underdog müssen im Team sein
    if new_captain_id not in new_player_ids or new_underdog_id not in new_player_ids:
        raise HTTPException(
            status_code=400,
            detail="Captain and Underdog must be in the selected player list.",
        )

    champion_player = (
        db.query(models.Player).filter(models.Player.id == new_champion_id).first()
    )
    if not champion_player:
        raise HTTPException(status_code=404, detail="Champion Pick player not found.")

    team.champion_id = new_champion_id

    db.query(models.TeamPlayer).filter(models.TeamPlayer.team_id == team_id).delete(
        synchronize_session=False
    )
    db.flush()

    for pid in new_player_ids:
        is_captain = pid == new_captain_id
        is_underdog = pid == new_underdog_id

        db.add(
            models.TeamPlayer(
                team_id=team_id,
                player_id=pid,
                is_captain=is_captain,
                is_underdog=is_underdog,
            )
        )

    db.commit()
    return {"message": "Team updated successfully", "team_id": team_id}


@router.get("/{team_id}/players")
def get_team_players(team_id: int, db: Session = Depends(get_db)):
    team_player_links = (
        db.query(models.TeamPlayer).filter(models.TeamPlayer.team_id == team_id).all()
    )
    if not team_player_links:
        return []

    link_map = {link.player_id: link for link in team_player_links}
    player_ids = list(link_map.keys())
    players = db.query(models.Player).filter(models.Player.id.in_(player_ids)).all()

    return [
        {
            "seed": p.seed,
            "name": p.name,
            "price": p.price,
            "nation": p.nation,
            "id": p.id,
            "points": p.points,
            "eliminated": p.eliminated,
            "is_captain": link_map[p.id].is_captain,
            "is_underdog": link_map[p.id].is_underdog,
            "champion": p.champion,
        }
        for p in players
    ]


@router.get("/{team_id}/champion_tip")
def get_team_champion_tip(team_id: int, db: Session = Depends(get_db)):
    team = db.query(models.Team).filter(models.Team.id == team_id).first()

    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    champion_id = team.champion_id

    if not champion_id:
        return None

    champion_player = (
        db.query(models.Player).filter(models.Player.id == champion_id).first()
    )

    if not champion_player:
        return None

    return {
        "seed": champion_player.seed,
        "name": champion_player.name,
        "price": champion_player.price,
        "nation": champion_player.nation,
        "id": champion_player.id,
        "points": champion_player.points,
        "eliminated": champion_player.eliminated,
        "is_champion": champion_player.champion,
    }


@router.get("/user/{user_id}")
def get_teams_by_user(user_id: int, db: Session = Depends(get_db)):
    teams = db.query(models.Team).filter(models.Team.user_id == user_id).all()

    result = []
    for t in teams:
        # Summe aller Punkte der Spieler im Team
        total_points = (
            db.query(models.Player.points)
            .join(models.TeamPlayer, models.Player.id == models.TeamPlayer.player_id)
            .filter(models.TeamPlayer.team_id == t.id)
            .all()
        )
        total_points_sum = sum(p[0] for p in total_points) if total_points else 0

        result.append(
            {
                "team_id": t.id,
                "team_name": t.name,
                "total_points": total_points_sum,
            }
        )

    return result


@router.delete("/{team_id}")
def delete_team(team_id: int, db: Session = Depends(get_db)):
    team = db.query(models.Team).filter(models.Team.id == team_id).first()
    if not team:
        return {"detail": "Team not found"}, 404

    # Lösche zugehörige TeamPlayer
    db.query(models.TeamPlayer).filter(models.TeamPlayer.team_id == team_id).delete()
    db.delete(team)
    db.commit()
    return {"detail": "Team deleted successfully"}


class TeamNameCheck(BaseModel):
    team_name: str


@router.post("/check_name")
def check_team_name_availability(
    # Erwarte das TeamNameCheck-Objekt im Request-Body
    data: TeamNameCheck,
    db: Session = Depends(get_db),
):
    team_name = data.team_name  # Zugriff auf den Namen aus dem Body

    # Datenbankabfrage
    team = db.query(models.Team).filter(models.Team.name == team_name).first()

    if team:
        # 409 Conflict senden, wenn der Name belegt ist
        raise HTTPException(
            status_code=409, detail=f"Team name '{team_name}' is already taken."
        )

    # 200 OK senden, wenn der Name frei ist
    return {"message": "Team name available"}


@router.post("/{team_id}/activate")
def set_active_team(
    team_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Setzt das angegebene Team als das aktive Team für den aktuellen Benutzer.
    """

    team_to_activate = db.get(models.Team, team_id)

    if not team_to_activate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )

    if team_to_activate.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this team"
        )

    current_user.active_team = team_to_activate

    db.commit()
    db.refresh(current_user)

    return {
        "message": f"Team '{team_to_activate.name}' is now the active team.",
        "active_team_id": current_user.active_team_id,
    }
