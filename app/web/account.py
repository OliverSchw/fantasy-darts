import hmac

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth, models
from ..db import get_db
from ..config_store import invite_code
from .common import State, flash, get_state, redirect, render

router = APIRouter()

MIN_PASSWORD = 6


def _safe_next(url: str | None) -> str:
    return url if url and url.startswith("/") and not url.startswith("//") else "/"


@router.get("/login")
def login_form(request: Request, next: str | None = None, db: Session = Depends(get_db)):
    return render(request, "login.html", next=_safe_next(next), invite_enabled=bool(invite_code(db)))


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(models.User).where(func.lower(models.User.username) == username.strip().lower()))
    if user is None or not auth.verify_password(password, user.password_hash):
        return render(request, "login.html", status_code=401, next=_safe_next(next),
                      error="Wrong username or password.", username=username,
                      invite_enabled=bool(invite_code(db)))
    auth.login(request, user)
    return redirect(_safe_next(next))


@router.post("/logout")
def logout(request: Request):
    auth.logout(request)
    return redirect("/")


@router.get("/account")
def account(request: Request, state: State = Depends(get_state), user: models.User = Depends(auth.require_user)):
    return render(request, "account.html", state)


@router.post("/account/password")
def change_password(
    request: Request,
    current: str = Form(...),
    new: str = Form(...),
    repeat: str = Form(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_user),
):
    if not auth.verify_password(current, user.password_hash):
        flash(request, "Current password is wrong.", "error")
    elif len(new) < MIN_PASSWORD:
        flash(request, f"New password must have at least {MIN_PASSWORD} characters.", "error")
    elif new != repeat:
        flash(request, "The new passwords don't match.", "error")
    else:
        user.password_hash = auth.hash_password(new)
        db.commit()
        flash(request, "Password changed.")
    return redirect("/account")


# ------------------------------------------------------------ Registrierung mit Einladungscode


def _invite_code(db: Session) -> str:
    code = invite_code(db)
    if not code:
        raise HTTPException(404)
    return code


@router.get("/register")
def register_form(request: Request, code: str = "", db: Session = Depends(get_db)):
    _invite_code(db)
    return render(request, "register.html", code=code)


@router.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db),
):
    expected = _invite_code(db)
    username = username.strip()
    error = None
    if not hmac.compare_digest(code.strip().encode(), expected.encode()):
        error = "Wrong invite code."
    elif not username or len(username) > 40:
        error = "Username must be 1-40 characters."
    elif len(password) < MIN_PASSWORD:
        error = f"Password must have at least {MIN_PASSWORD} characters."
    elif db.scalar(select(models.User).where(func.lower(models.User.username) == username.lower())):
        error = "Username already taken."
    if error:
        return render(request, "register.html", status_code=400, error=error, username=username, code=code)
    user = models.User(username=username, password_hash=auth.hash_password(password))
    db.add(user)
    db.commit()
    auth.login(request, user)
    flash(request, f"Welcome, {username}! Now build your team.")
    return redirect("/my")
