"""Seite "Confirm": offene Bestätigungen annehmen/ablehnen, Einstellung im Account."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import confirmations, models
from ..auth import require_user
from ..db import get_db
from .common import flash, redirect, render

router = APIRouter()


@router.get("/confirm")
def confirm_page(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    items = []
    for c in confirmations.pending_for(db, user):
        info = confirmations.describe(db, c)
        if info is None:  # Spiel/Turnier gibt es nicht mehr
            db.delete(c)
            continue
        items.append({"c": c, **info})
    db.commit()
    return render(request, "confirm.html", user=user, items=items)


def _back(request: Request, fallback: str = "/confirm") -> str:
    nxt = str(request.query_params.get("next", ""))
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else fallback


@router.post("/confirm/{kind}/{ref_id:int}/{answer}")
def confirm_answer(kind: str, ref_id: int, answer: str, request: Request, db: Session = Depends(get_db),
                   user: models.User = Depends(require_user)):
    if kind not in confirmations.KINDS or answer not in ("accept", "decline"):
        raise HTTPException(404)
    if answer == "accept":
        if confirmations.accept(db, user, kind, ref_id):
            flash(request, "✓ Confirmed – it counts for you.")
    elif confirmations.decline(db, user, kind, ref_id):
        flash(request, "Removed – you were replaced by a guest, nothing counts for you.")
    return redirect(_back(request))


@router.post("/account/confirm-games")
async def set_confirm_games(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    form = await request.form()
    user.confirm_games = bool(form.get("on"))
    if not user.confirm_games:  # ausgeschaltet: alles Offene zählt ab sofort
        for c in confirmations.pending_for(db, user):
            db.delete(c)
    db.commit()
    flash(request, "From now on you confirm games others add you to." if user.confirm_games
          else "Games others add you to count right away again.")
    return redirect("/account")
