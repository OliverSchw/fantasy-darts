import csv
from app import models, database


# def add_players_from_csv():
#     db = database.SessionLocal()
#     with open("players_2025.csv", newline="", encoding="utf-8") as file:
#         reader = csv.DictReader(file)
#         for row in reader:
#             player = models.Player(
#                 seed=int(row.get("seed", 0)),
#                 name=row["name"],
#                 price=float(row["price"]),
#                 nation=row.get("nation", ""),
#             )
#             db.add(player)
#         db.commit()
#         db.close()
def add_players_from_csv():
    db = database.SessionLocal()
    try:
        with open("players_2025.csv", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                # Check if the player already exists
                existing = (
                    db.query(models.Player)
                    .filter(models.Player.name == row["name"])
                    .first()
                )
                if existing:
                    print(f"Player '{row['name']}' already exists, skipping")
                    continue

                player = models.Player(
                    seed=int(row.get("seed", 0)),
                    name=row["name"],
                    price=float(row["price"]),
                    nation=row.get("nation", ""),
                )
                db.add(player)
            db.commit()
            print("All new players have been added")
    finally:
        db.close()


if __name__ == "__main__":
    add_players_from_csv()
