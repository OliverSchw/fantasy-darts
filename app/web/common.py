"""Gemeinsames für alle Seiten: Templates, Flash-Nachrichten, geladener Saison-Zustand."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import cached_property
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import models
from ..auth import optional_user
from ..bracket_view import Bracket, PlayerStatus
from ..db import get_db
from ..flags import flag_code
from ..rules import Rules, current_rules
from ..scoring import PlayerScore, TeamScore, champion_id, player_scores, team_score
from ..season import get_season, is_locked, season_matches, season_players
from ..settings import get_settings

templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


def _fmt_points(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".") if value == int(value) else f"{value:,.1f}"


def _fmt_price(value: float) -> str:
    return f"{value:.1f}"


templates.env.filters["pts"] = _fmt_points
templates.env.filters["price"] = _fmt_price
templates.env.globals["flag_code"] = flag_code


def local_date(dt: datetime | None) -> date | None:
    """Datum in der lokalen Zeitzone. SQLite liefert naive Zeiten -> als UTC behandeln."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(get_settings().timezone)).date()


def flash(request: Request, message: str, category: str = "ok") -> None:
    request.session.setdefault("flash", []).append([category, message])


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


@dataclass
class State:
    """Alles, was die Seiten zur aktiven Saison brauchen - einmal pro Request geladen."""

    db: Session
    season: models.Season
    rules: Rules
    user: models.User | None

    @cached_property
    def locked(self) -> bool:
        return is_locked(self.season, self.rules)

    @cached_property
    def players(self) -> dict[int, models.Player]:
        return season_players(self.db, self.season)

    @cached_property
    def matches(self) -> list[models.Match]:
        return season_matches(self.db, self.season)

    @cached_property
    def scores(self) -> dict[int, PlayerScore]:
        return player_scores(self.rules, self.matches)

    @cached_property
    def champion_id(self) -> int | None:
        return champion_id(self.scores)

    def score(self, player_id: int) -> PlayerScore:
        return self.scores.get(player_id) or PlayerScore()

    def team_score(self, team: models.Team) -> TeamScore:
        return team_score(self.rules, team, self.scores)

    def can_view_team(self, team: models.Team) -> bool:
        """Fremde Teams sind erst nach dem Sperren sichtbar."""
        if self.locked:
            return True
        return self.user is not None and (self.user.is_admin or self.user.id == team.user_id)

    @cached_property
    def active_teams(self) -> list[models.Team]:
        return list(
            self.db.scalars(
                select(models.Team)
                .options(joinedload(models.Team.user))
                .where(models.Team.season_id == self.season.id, models.Team.is_active.is_(True))
            ).unique()
        )

    @cached_property
    def bracket(self) -> Bracket:
        return Bracket(self.rules, self.matches, self.players)

    def status(self, player_id: int) -> PlayerStatus:
        return self.bracket.status(player_id)

    @cached_property
    def my_team(self) -> models.Team | None:
        if self.user is None:
            return None
        return next((t for t in self.active_teams if t.user_id == self.user.id), None)

    @cached_property
    def my_player_ids(self) -> set[int]:
        return set(self.my_team.player_ids) if self.my_team else set()

    def _ranked(self, scores: dict[int, PlayerScore]) -> list[dict]:
        rows = []
        for t in self.active_teams:
            sc = team_score(self.rules, t, scores)
            alive = sum(1 for pid in t.player_ids if not (scores.get(pid) or PlayerScore()).eliminated)
            rows.append({"team": t, "points": sc.total, "alive": alive})
        rows.sort(key=lambda r: (-r["points"], r["team"].name.lower()))
        rank, prev = 0, None
        for i, r in enumerate(rows, start=1):
            if r["points"] != prev:
                rank, prev = i, r["points"]
            r["rank"] = rank
        return rows

    def leaderboard(self) -> list[dict]:
        """Ranking inkl. Bewegung seit dem letzten Spieltag (Tag mit eingetragenen Ergebnissen)."""
        rows = self._ranked(self.scores)
        played = [m for m in self.matches if m.is_played]
        days = sorted({local_date(m.updated_at) for m in played if m.updated_at})
        if len(days) >= 2:
            before = [m for m in played if m.updated_at and local_date(m.updated_at) < days[-1]]
            prev_rank = {r["team"].id: r["rank"] for r in self._ranked(player_scores(self.rules, before))}
            for r in rows:
                r["move"] = prev_rank.get(r["team"].id, r["rank"]) - r["rank"]
        return rows

    def latest_results(self, limit: int = 6) -> list[models.Match]:
        played = [m for m in self.matches if m.is_played and m.updated_at]
        played.sort(key=lambda m: m.updated_at, reverse=True)
        return played[:limit]


def get_state(
    db: Session = Depends(get_db), user: models.User | None = Depends(optional_user)
) -> State:
    return State(db=db, season=get_season(db), rules=current_rules(), user=user)


def render(request: Request, template: str, state: State | None = None, status_code: int = 200, **ctx):
    flashes = request.session.pop("flash", [])
    base = {
        "flashes": flashes,
        "user": state.user if state else None,
        "rules": state.rules if state else current_rules(),
        "state": state,
        "path": request.url.path,
        "invite_enabled": bool(get_settings().invite_code),
    }
    return templates.TemplateResponse(request, template, {**base, **ctx}, status_code=status_code)
