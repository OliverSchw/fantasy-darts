import requests

# Basis-URL deiner FastAPI-App
BASE_URL = "http://127.0.0.1:8000"

# Spieler-ID
player_id = 32  # ersetze mit der ID des Spielers

# Stats für diesen Spieler
stats = {
    "is_winner": True,
    "sets_won": 3,
    "legs_won": 9,
    "180s": 2,
    "high_checkout": 100,
    "average": 95,
    "checkout_pct": 42,
}

# Request an den Endpoint senden
response = requests.put(f"{BASE_URL}/points/player/{player_id}", json=stats)

# Ergebnis ausgeben
if response.status_code == 200:
    print("✅ Points added successfully!")
    print(response.json())
else:
    print("❌ Error adding points:")
    print(response.text)
