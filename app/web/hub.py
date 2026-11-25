"""Startseite der Plattform (Auswahl der Bereiche) und Admin-Übersicht über alle Bereiche."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import feed, models
from ..auth import optional_user, require_admin
from ..config_store import season_rules
from ..db import get_db
from ..platform import SECTIONS
from ..season import SeasonNotImported, get_season
from .common import State, render

router = APIRouter()


def _fantasy_status(db: Session, user: models.User | None) -> dict | None:
    """Kurzinfo für die Fantasy-Kachel: eigener Platz bzw. ob man noch ein Team bauen kann."""
    try:
        season = get_season(db)
    except SeasonNotImported:
        return None
    state = State(db=db, season=season, rules=season_rules(db, season), user=user)
    rows = state.leaderboard()
    mine = next((r for r in rows if user and r["team"].user_id == user.id), None)
    return {"rows": len(rows), "mine": mine, "locked": state.locked, "competition": state.rules.name}


@router.get("/")
def home(request: Request, db: Session = Depends(get_db), user: models.User | None = Depends(optional_user)):
    live = db.scalar(select(func.count()).select_from(models.DartsGame).where(models.DartsGame.status == "live"))
    bp_live = db.scalar(select(func.count()).select_from(models.BeerpongGame).where(models.BeerpongGame.status == "live"))
    status = {"fantasy": _fantasy_status(db, user), "darts": {"live": live}, "beerpong": {"live": bp_live}}
    return render(request, "hub.html", user=user, status=status, news=feed.news(db, limit=8) if user else [])


@router.get("/admin")
def admin_home(request: Request, db: Session = Depends(get_db), admin: models.User = Depends(require_admin)):
    n_users = db.scalar(select(func.count()).select_from(models.User))
    n_open = db.scalar(select(func.count()).select_from(models.Invite).where(models.Invite.used_at.is_(None)))
    return render(request, "admin_home.html", user=admin, n_users=n_users, n_open_invites=n_open,
                  admin_sections=[s for s in SECTIONS if s.ready and s.admin_href])
