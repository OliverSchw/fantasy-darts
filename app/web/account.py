import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import auth, models
from ..avatars import MAX_UPLOAD, AvatarError, delete_avatar, save_avatar
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


# ------------------------------------------------------------ Profilbild


@router.post("/account/avatar")
async def upload_avatar(
    request: Request,
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_user),
):
    data = await image.read(MAX_UPLOAD + 1)
    try:
        save_avatar(db, user, data)
        flash(request, "Profile picture saved.")
    except AvatarError as e:
        db.rollback()
        flash(request, str(e), "error")
    return redirect("/account")


@router.post("/account/avatar/delete")
def remove_avatar(request: Request, db: Session = Depends(get_db), user: models.User = Depends(auth.require_user)):
    delete_avatar(db, user)
    flash(request, "Profile picture removed.")
    return redirect("/account")


@router.get("/avatars/{user_id}")
def avatar_image(user_id: int, db: Session = Depends(get_db), viewer: models.User = Depends(auth.require_user)):
    """Nur für eingeloggte Mitspieler. Die URL enthält ?v=<version>, deshalb darf lange gecacht werden."""
    avatar = db.get(models.Avatar, user_id)
    if avatar is None:
        raise HTTPException(404)
    return Response(avatar.image, media_type="image/webp", headers={
        "Cache-Control": "private, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
    })


# ------------------------------------------------------------ Registrierung
#
# Zwei Wege: der gemeinsame Einladungscode (?code=...) oder ein persönlicher
# Einmal-Link (?invite=<token>), den der Admin pro Mitspieler erzeugt.


def _invite_code(db: Session) -> str:
    code = invite_code(db)
    if not code:
        raise HTTPException(404)
    return code


def _open_invite(db: Session, token: str) -> models.Invite | None:
    inv = db.scalar(select(models.Invite).where(models.Invite.token == token))
    return inv if inv is not None and inv.used_at is None else None


def _invite_gone(request: Request):
    return render(request, "message.html", status_code=410, title="Invite link not valid",
                  text="This invite link was already used or is no longer valid. "
                       "Ask the admin for a new one.")


@router.get("/register")
def register_form(request: Request, code: str = "", invite: str = "", db: Session = Depends(get_db)):
    if invite:
        if _open_invite(db, invite) is None:
            return _invite_gone(request)
        return render(request, "register.html", invite=invite)
    _invite_code(db)
    return render(request, "register.html", code=code)


@router.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    code: str = Form(""),
    invite: str = Form(""),
    db: Session = Depends(get_db),
):
    username = username.strip()
    inv = None
    code_ok = True
    if invite:
        inv = _open_invite(db, invite)
        if inv is None:
            return _invite_gone(request)
    else:
        code_ok = hmac.compare_digest(code.strip().encode(), _invite_code(db).encode())
    error = None
    if not code_ok:
        error = "Wrong invite code."
    elif not username or len(username) > 40:
        error = "Username must be 1-40 characters."
    elif len(password) < MIN_PASSWORD:
        error = f"Password must have at least {MIN_PASSWORD} characters."
    elif db.scalar(select(models.User).where(func.lower(models.User.username) == username.lower())):
        error = "Username already taken."
    if error:
        # Fehler verbrauchen den Link nicht: bis hierhin wurde nichts geschrieben.
        return render(request, "register.html", status_code=400, error=error, username=username,
                      code=code, invite=invite)

    user = models.User(username=username, password_hash=auth.hash_password(password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:  # gleichzeitig derselbe Name registriert
        db.rollback()
        return render(request, "register.html", status_code=400, error="Username already taken.",
                      username=username, code=code, invite=invite)
    if inv is not None:
        # Bedingtes UPDATE: nur ein einziger Request kann den Link einlösen, auch bei Parallelzugriff.
        result = db.execute(
            update(models.Invite)
            .where(models.Invite.id == inv.id, models.Invite.used_at.is_(None))
            .values(used_at=datetime.now(timezone.utc), used_by_id=user.id)
        )
        if result.rowcount != 1:
            db.rollback()  # User wird mit zurückgerollt
            return _invite_gone(request)
    db.commit()
    auth.login(request, user)
    flash(request, f"Welcome, {username}! Now build your team.")
    return redirect("/my")
