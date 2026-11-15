"""Passwörter und Login-Session (signiertes Cookie)."""

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
