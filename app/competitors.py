"""Kern: Teilnehmer an Spielen (Darts, Bierpong) - Mitglieder mit Konto oder Gäste mit Namen."""

import random

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models


class CompetitorError(ValueError):
    """Meldung für den User."""


def ensure_user_competitors(db: Session) -> None:
    """Jedes Konto bekommt automatisch einen Teilnehmer (damit man Mitglieder direkt auswählen kann)."""
    have = set(db.scalars(select(models.Competitor.user_id).where(models.Competitor.user_id.is_not(None))))
    missing = [u for u in db.scalars(select(models.User)) if u.id not in have]
    for u in missing:
        db.add(models.Competitor(name=u.username, user_id=u.id))
    if missing:
        db.commit()


def competitor_for_user(db: Session, user: models.User) -> models.Competitor:
    c = db.scalar(select(models.Competitor).where(models.Competitor.user_id == user.id))
    if c is None:
        c = models.Competitor(name=user.username, user_id=user.id)
        db.add(c)
        db.commit()
    return c


def all_competitors(db: Session) -> list[models.Competitor]:
    """Mitglieder und Gäste (ohne Bots - die stehen in keiner Auswahl- oder Rangliste)."""
    ensure_user_competitors(db)
    rows = db.scalars(select(models.Competitor).where(models.Competitor.bot_level.is_(None))).unique().all()
    return sorted(rows, key=lambda c: (c.is_guest, c.display_name.lower()))


def bot(db: Session, level: str) -> models.Competitor:
    """Den Bot dieser Stärke holen (wird beim ersten Mal angelegt)."""
    from .darts.bot import LEVELS
    if level not in LEVELS:
        raise CompetitorError("Unknown bot level.")
    c = db.scalar(select(models.Competitor).where(models.Competitor.bot_level == level))
    if c is None:
        c = models.Competitor(name=LEVELS[level].name, bot_level=level)
        db.add(c)
        db.flush()
    return c


def name_taken(db: Session, name: str) -> bool:
    low = name.strip().lower()
    if db.scalar(select(models.User.id).where(func.lower(models.User.username) == low)):
        return True
    if low in {lv.name.lower() for lv in _bot_levels().values()}:
        return True  # "Pro Bot" & Co. sind reserviert
    return db.scalar(select(models.Competitor.id).where(
        models.Competitor.user_id.is_(None), func.lower(models.Competitor.name) == low)) is not None


def _bot_levels():
    from .darts.bot import LEVELS
    return LEVELS


def create_guest(db: Session, name: str) -> models.Competitor:
    name = " ".join(name.split())
    if not 1 <= len(name) <= 40:
        raise CompetitorError("Guest names must be 1-40 characters.")
    if name_taken(db, name):
        raise CompetitorError(f"“{name}” already exists – pick them from the list.")
    c = models.Competitor(name=name)
    db.add(c)
    db.flush()
    return c


# ---------------------------------------------------------------- Teams (Bierpong, Darts-Doppel)


def parse_teams(db: Session, text: str) -> tuple[list[list[int]], list[str | None]]:
    """Feste Teams aus Textzeilen: "Teamname: Olli, Kevin" oder nur "Olli, Kevin".
    Namen von Mitgliedern/Gästen werden erkannt, unbekannte Namen werden neue Gäste."""
    teams, names = [], []
    for line in [ln.strip() for ln in text.splitlines() if ln.strip()]:
        team_name, _, members = line.rpartition(":")
        people = [p.strip() for p in members.replace("&", ",").replace("+", ",").split(",") if p.strip()]
        if not people:
            raise CompetitorError(f"No players in the line “{line}”.")
        ids = [_find_or_create(db, p) for p in people]
        teams.append(ids)
        names.append(" ".join(team_name.split()) or None)
    return teams, names


def _find_or_create(db: Session, name: str) -> int:
    low = name.lower()
    user = db.scalar(select(models.User).where(func.lower(models.User.username) == low))
    if user is not None:
        return competitor_for_user(db, user).id
    guest = db.scalar(select(models.Competitor).where(
        models.Competitor.user_id.is_(None), func.lower(models.Competitor.name) == low))
    return guest.id if guest else create_guest(db, name).id


def random_pairs(ids: list[int]) -> list[list[int]]:
    if len(ids) < 4 or len(ids) % 2:
        raise CompetitorError("Random teams of 2 need an even number of players (at least 4).")
    ids = list(ids)
    random.shuffle(ids)
    return [ids[i:i + 2] for i in range(0, len(ids), 2)]
