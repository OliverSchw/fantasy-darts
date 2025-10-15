from fastapi import FastAPI
from .database import Base, engine
from .models import *
from .routes import players, teams, matches, leaderboard, auth, add_points
from fastapi.middleware.cors import CORSMiddleware

# Base.metadata.create_all(bind=engine)

app = FastAPI(title="Fantasy Darts")

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

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
