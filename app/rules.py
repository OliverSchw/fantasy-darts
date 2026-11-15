"""Lädt und validiert die Spielregeln einer Saison aus seasons/<key>/rules.toml."""

import tomllib
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from .settings import get_settings


class Role(BaseModel):
    label: str
    max_price: float
    multiplier: float = 2


class ChampionPick(BaseModel):
    bonus: float = 50


class TeamRules(BaseModel):
    budget: float
    squad_size: int = Field(gt=0)
    max_teams_per_user: int = Field(default=5, gt=0)
    playmaker: Role
    underdog: Role
    champion_pick: ChampionPick = ChampionPick()


class Tournament(BaseModel):
    round_names: list[str]
    sets_to_win: list[int]

    @property
    def num_rounds(self) -> int:
        return len(self.round_names)


class Stat(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str
    points: float


class Scoring(BaseModel):
    per_set_won: float = 0
    per_set_margin_winner: float = 0
    round_win_bonus: list[float] = []
    stats: list[Stat] = []


class Rules(BaseModel):
    name: str
    lock_at: datetime | None = None
    team: TeamRules
    tournament: Tournament
    scoring: Scoring

    @model_validator(mode="before")
    @classmethod
    def _empty_lock_at(cls, data):
        if isinstance(data, dict) and data.get("lock_at") == "":
            data = {**data, "lock_at": None}
        return data

    @model_validator(mode="after")
    def _check_lengths(self):
        n = self.tournament.num_rounds
        if len(self.tournament.sets_to_win) != n:
            raise ValueError("tournament.sets_to_win muss genauso viele Einträge haben wie round_names")
        if self.scoring.round_win_bonus and len(self.scoring.round_win_bonus) != n:
            raise ValueError("scoring.round_win_bonus muss genauso viele Einträge haben wie round_names")
        if self.lock_at is not None and self.lock_at.tzinfo is None:
            raise ValueError("lock_at braucht eine Zeitzone, z.B. +01:00")
        keys = [s.key for s in self.scoring.stats]
        if len(keys) != len(set(keys)):
            raise ValueError("scoring.stats: keys müssen eindeutig sein")
        return self

    def round_bonus(self, round_no: int) -> float:
        b = self.scoring.round_win_bonus
        return b[round_no - 1] if b else 0

    def matches_in_round(self, round_no: int) -> int:
        return 2 ** (self.tournament.num_rounds - round_no)


def season_dir(key: str) -> Path:
    return get_settings().seasons_dir / key


@lru_cache
def load_rules(key: str) -> Rules:
    with open(season_dir(key) / "rules.toml", "rb") as f:
        return Rules.model_validate(tomllib.load(f))


def current_rules() -> Rules:
    return load_rules(get_settings().season)
