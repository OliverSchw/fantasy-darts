"""Kern: Teilnehmer an Spielen (Darts, Bierpong) - Mitglieder mit Konto oder Gäste mit Namen."""

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
    ensure_user_competitors(db)
    rows = db.scalars(select(models.Competitor)).unique().all()
    return sorted(rows, key=lambda c: (c.is_guest, c.display_name.lower()))


def name_taken(db: Session, name: str) -> bool:
    low = name.strip().lower()
    if db.scalar(select(models.User.id).where(func.lower(models.User.username) == low)):
        return True
    return db.scalar(select(models.Competitor.id).where(
        models.Competitor.user_id.is_(None), func.lower(models.Competitor.name) == low)) is not None


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
