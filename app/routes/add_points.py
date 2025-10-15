from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .. import models, database

router = APIRouter(prefix="/points", tags=["points"])


# --- Datenbank-Session ---
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Punkteberechnung ---
def calculate_points(stats: dict) -> float:
    pts = 0
    if stats.get("is_winner"):
        pts += 50
    pts += stats.get("sets_won", 0) * 12
    pts += stats.get("legs_won", 0) * 4
    pts += stats.get("180s", 0) * 8
    if stats.get("high_checkout", 0) >= 100:
        pts += 10
    if stats.get("average", 0) > 90:
        pts += 5
    if stats.get("average", 0) > 100:
        pts += 5
    if stats.get("checkout_pct", 0) > 40:
        pts += 5
    return pts


# --- Punkte auf Spieler anwenden ---
@router.put("/player/{player_id}")
def add_points_player(player_id: int, stats: dict, db: Session = Depends(get_db)):
    """
    Berechnet Punkte anhand von Match-Stats und addiert sie auf den Spielerpreis und Punkte.
    `stats` ist ein dict mit Keys: is_winner, sets_won, legs_won, 180s, high_checkout, average, checkout_pct
    """
    player = db.query(models.Player).filter(models.Player.id == player_id).first()
    if not player:
        return {"error": "Player not found"}

    additional_points = calculate_points(stats)

    # Punkte auf price addieren
    player.price += additional_points
    player.points += additional_points

    db.commit()
    db.refresh(player)

    return {
        "id": player.id,
        "name": player.name,
        "added_points": additional_points,
        "new_price": player.price,
        "total_points": player.points,
    }
