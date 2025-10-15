import csv
from app import models, database


def add_players_from_csv():
    db = database.SessionLocal()
    with open("players_2025.csv", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            player = models.Player(
                seed=int(row.get("seed", 0)),
                name=row["name"],
                price=float(row["price"]),
                nation=row.get("nation", ""),
            )
            db.add(player)
        db.commit()
        db.close()


if __name__ == "__main__":
    add_players_from_csv()
