from fastapi import FastAPI
from .database import Base, engine
from .models import *
from .routes import players, teams, matches, leaderboard, auth, add_points
from fastapi.middleware.cors import CORSMiddleware

# Base.metadata.create_all(bind=engine)

app = FastAPI(title="Fantasy Darts")


@app.on_event("startup")
def startup_event():
    # Tabellen erstellen
    Base.metadata.create_all(bind=engine)

    # Benutzer / Spieler initialisieren
    from .add_players import add_players_from_csv
    from .create_users import create_user

    # User nur erstellen, wenn sie noch nicht existieren (idempotent)
    create_user("olli", "bla123")
    create_user("maria", "passwort123")
    create_user("Dagey", "Hund123")
    add_players_from_csv()


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*"
    ],  # oder später gezielt: ["https://fantasy-darts-frontend.streamlit.app"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {"msg": "Fantasy Darts läuft!"}


app.include_router(add_points.router)
app.include_router(auth.router)
app.include_router(players.router)
app.include_router(teams.router)
app.include_router(matches.router)
app.include_router(leaderboard.router)
