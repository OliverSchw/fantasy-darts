"""Passwörter und Login-Session (signiertes Cookie)."""

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from . import models
from .db import get_db


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


# ---------------------------------------------------------------- Schutz gegen Passwort-Raten

MAX_FAILURES = 10
WINDOW = timedelta(minutes=15)
LOCK_FOR = timedelta(minutes=15)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def login_locked_minutes(db: Session, username: str) -> int:
    """Minuten, die dieser Username noch gesperrt ist (0 = nicht gesperrt)."""
    row = db.get(models.LoginThrottle, username.strip().lower()[:40])
    until = _aware(row.locked_until) if row else None
    now = datetime.now(timezone.utc)
    return max(1, round((until - now).total_seconds() / 60)) if until and until > now else 0


def record_login_failure(db: Session, username: str) -> None:
    key = username.strip().lower()[:40]
    now = datetime.now(timezone.utc)
    row = db.get(models.LoginThrottle, key)
    if row is None:
        row = models.LoginThrottle(key=key, failures=0, window_start=now)
        db.add(row)
    if now - _aware(row.window_start) > WINDOW:
        row.failures, row.window_start, row.locked_until = 0, now, None
    row.failures += 1
    if row.failures >= MAX_FAILURES:
        row.locked_until = now + LOCK_FOR
    db.commit()


def clear_login_failures(db: Session, username: str) -> None:
    row = db.get(models.LoginThrottle, username.strip().lower()[:40])
    if row is not None:
        db.delete(row)
        db.commit()


class LoginRequired(Exception):
    pass


class AdminRequired(Exception):
    pass


def login(request: Request, user: models.User) -> None:
    request.session.clear()
    request.session["uid"] = user.id


def logout(request: Request) -> None:
    request.session.clear()


def optional_user(request: Request, db: Session = Depends(get_db)) -> models.User | None:
    uid = request.session.get("uid")
    if uid is None:
        return None
    user = db.get(models.User, uid)
    if user is None:
        request.session.clear()
    return user


def require_user(user: models.User | None = Depends(optional_user)) -> models.User:
    if user is None:
        raise LoginRequired()
    return user


def require_admin(user: models.User = Depends(require_user)) -> models.User:
    if not user.is_admin:
        raise AdminRequired()
    return user
