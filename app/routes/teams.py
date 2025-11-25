from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .. import database, models
from ..schemas import TeamCreate


router = APIRouter(prefix="/teams", tags=["teams"])


def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


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

    underdog_player = (
        db.query(models.Player).filter(models.Player.id == team.underdog_id).first()
    )
    if not underdog_player or underdog_player.price >= 800.0:
        raise HTTPException(
            status_code=400, detail="Underdog must have a price less than 800.0."
        )

    new_team = models.Team(name=team.team_name, user_id=team.user_id)
    db.add(new_team)
    db.commit()
    db.refresh(new_team)

    for pid in team.player_ids:
        # Setze is_captain/is_underdog basierend auf den übergebenen IDs
        is_captain = pid == team.captain_id
        is_underdog = pid == team.underdog_id

        db.add(
            models.TeamPlayer(
                team_id=new_team.id,
                player_id=pid,
                is_captain=is_captain,  # NEU
                is_underdog=is_underdog,  # NEU
            )
        )
    db.commit()

    return {"team_id": new_team.id, "team_name": new_team.name}


@router.put("/{team_id}")
def update_team(team_id: int, payload: dict, db: Session = Depends(get_db)):
    # Team suchen
    team = db.query(models.Team).filter(models.Team.id == team_id).first()
    if not team:
        return {"detail": "Not Found"}

    # Alte Spieler-Zuordnungen löschen
    db.query(models.TeamPlayer).filter(models.TeamPlayer.team_id == team_id).delete()

    # Neue Spieler hinzufügen
    new_player_ids = payload.get("player_ids", [])
    for pid in new_player_ids:
        db.add(models.TeamPlayer(team_id=team_id, player_id=pid))

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
        }
        for p in players
    ]


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
