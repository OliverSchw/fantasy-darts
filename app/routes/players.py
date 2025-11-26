from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .. import database, models

router = APIRouter(prefix="/players", tags=["players"])


# --- DB Session Helper ---
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- GET: alle Spieler ---
@router.get("/")
def get_players(db: Session = Depends(get_db)):
    players = db.query(models.Player).all()
    # Konvertiere SQLAlchemy-Objekte in dicts für JSON
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


# --- POST: neuen Spieler hinzufügen ---
@router.post("/")
def add_player(
    name: str,
    price: float,
    nation: str = "",
    seed: int = 0,
    db: Session = Depends(get_db),
):
    player = models.Player(name=name, price=price, nation=nation, seed=seed)
    db.add(player)
    db.commit()
    db.refresh(player)
    return {
        "seed": player.seed,
        "name": player.name,
        "price": player.price,
        "nation": player.nation,
        "id": player.id,
    }


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

    player.points += additional_points
    if stats.get("is_winner") is False:
        player.eliminated = True
    db.commit()
    db.refresh(player)

    return {
        "id": player.id,
        "name": player.name,
        "added_points": additional_points,
        "new_price": player.price,
        "total_points": player.points,
    }


@router.put("/points/recompute")
def recompute_points(db: Session = Depends(get_db)):
    """
    Berechnet die Punkte aller Spieler basierend auf allen gespeicherten Matches.
    Setzt die Punkte neu und aktualisiert auch eliminierte Spieler.
    """
    players = db.query(models.Player).all()

    # Alle Spieler initial zurücksetzen
    for player in players:
        player.points = 0
        player.eliminated = False

    db.commit()

    # Alle Matches abrufen
    matches = db.query(models.Match).all()

    for match in matches:
        # Spieler 1
        player1 = (
            db.query(models.Player).filter(models.Player.id == match.p1_id).first()
        )
        if player1:
            stats_p1 = {
                "is_winner": match.winner_id == player1.id,
                "sets_won": match.sets_p1,
                "legs_won": match.legs_p1,
                "180s": match.d180s_p1,
                "high_checkout": match.high_checkout_p1,
                "average": match.average_p1,
                "checkout_pct": match.checkout_pct_p1,
            }
            points = calculate_points(stats_p1)
            player1.points += points
            if not stats_p1["is_winner"]:
                player1.eliminated = True

        # Spieler 2
        player2 = (
            db.query(models.Player).filter(models.Player.id == match.p2_id).first()
        )
        if player2:
            stats_p2 = {
                "is_winner": match.winner_id == player2.id,
                "sets_won": match.sets_p2,
                "legs_won": match.legs_p2,
                "180s": match.d180s_p2,
                "high_checkout": match.high_checkout_p2,
                "average": match.average_p2,
                "checkout_pct": match.checkout_pct_p2,
            }
            points = calculate_points(stats_p2)
            player2.points += points
            if not stats_p2["is_winner"]:
                player2.eliminated = True

    db.commit()
