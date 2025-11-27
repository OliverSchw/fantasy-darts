from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from .. import database, models

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])
CHAMPION_POINTS = 1000


# --- DB Session Helper ---
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/")
def leaderboard(db: Session = Depends(get_db)):
    # Lade Teams und verknüpfe sie sofort mit den TeamPlayern und den zugehörigen Playern
    # Dies ist effizienter, da es N+1 Queries vermeidet (Eager Loading)
    teams = (
        db.query(models.Team)
        .options(
            joinedload(models.Team.team_players).joinedload(models.TeamPlayer.player)
        )
        .all()
    )

    result = []

    for team in teams:
        total_points = 0

        for tp in team.team_players:
            # Stelle sicher, dass der Player existiert und Punkte hat (falls nicht null)
            if tp.player:
                player_points = tp.player.points

                weighted_points = player_points

                if tp.is_captain:
                    weighted_points += player_points

                if tp.is_underdog:
                    weighted_points += player_points

                if tp.champion:
                    weighted_points += CHAMPION_POINTS

                total_points += weighted_points

        result.append(
            {
                "team_id": team.id,
                "team_name": team.name,
                "user_id": team.user_id,
                "total_points": total_points,
            }
        )
    result.sort(key=lambda x: x["total_points"], reverse=True)

    return result
