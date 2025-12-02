from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .. import database, models

router = APIRouter(prefix="/players", tags=["players"])


def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/")
def get_players(db: Session = Depends(get_db)):
    players = db.query(models.Player).all()
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
    """is_winner,sets_won,sets_lost,p171s,p161finishes,ninedarters"""
    pts = 0
    # if stats.get("is_winner"):
    #     pts += 50
    pts += stats.get("sets_won", 0) * 20
    pts += stats.get("sets_lost", 0) * (-5)
    pts += stats.get("p171s", 0) * 1
    pts += stats.get("p161finishes", 0) * 3
    pts += stats.get("ninedarters", 0) * 100
    return pts


@router.put("/player/{player_id}")
def add_points_player(player_id: int, stats: dict, db: Session = Depends(get_db)):
    """Adds points to a player based on match statistics."""
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
    Computes the points of all players based on all stored matches.
    Resets the points and also updates eliminated players.
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
                "sets_lost": match.sets_p2,
                "p171s": match.p171s_p1,
                "p161finishes": match.p161finishes_p1,
                "ninedarters": match.ninedarter_p1,
            }
            points = calculate_points(stats_p1)
            player1.points += points
            if match.winner_id == player1.id and match.is_final:
                player1.champion = True
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
                "sets_lost": match.sets_p1,
                "p171s": match.p171s_p2,
                "p161finishes": match.p161finishes_p2,
                "ninedarters": match.ninedarter_p2,
            }
            points = calculate_points(stats_p2)
            player2.points += points
            if match.winner_id == player2.id and match.is_final:
                player2.champion = True
            if not stats_p2["is_winner"]:
                player2.eliminated = True

    db.commit()
