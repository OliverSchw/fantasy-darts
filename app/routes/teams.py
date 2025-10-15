from fastapi import APIRouter, Depends
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


@router.post("/")
def create_team(team: TeamCreate, db: Session = Depends(get_db)):
    new_team = models.Team(name=team.team_name, user_id=team.user_id)
    db.add(new_team)
    db.commit()
    db.refresh(new_team)

    for pid in team.player_ids:
        db.add(models.TeamPlayer(team_id=new_team.id, player_id=pid))
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
    # Alle Spieler-IDs des Teams holen
    team_player_links = (
        db.query(models.TeamPlayer).filter(models.TeamPlayer.team_id == team_id).all()
    )
    player_ids = [link.player_id for link in team_player_links]

    # Spieler-Daten abrufen
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
