from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .. import database, models

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


# --- DB Session Helper ---
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/")
def leaderboard(db: Session = Depends(get_db)):
    teams = db.query(models.Team).all()
    result = []
    for team in teams:
        total_points = sum(tp.player.points for tp in team.team_players if tp.player)
        result.append(
            {
                "team_id": team.id,
                "team_name": team.name,
                "user_id": team.user_id,
                "total_points": total_points,
            }
        )
    return result


# @router.get("/")
# def leaderboard(db: Session = Depends(get_db)):
#     # Dummy-Beispiel: eine Liste von Teams
#     results = [
#         {"team_id": 1, "team_name": "Team A", "user_id": 1, "total_points": 0},
#         {"team_id": 2, "team_name": "Team B", "user_id": 2, "total_points": 0},
#     ]
#     return results
