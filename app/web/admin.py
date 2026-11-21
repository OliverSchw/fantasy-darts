"""Admin: Ergebnisse eintragen, Teams sperren, User verwalten."""

import json
import secrets
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, select

from .. import models
from ..auth import hash_password, require_admin
from ..avatars import delete_avatar
from ..backup import export_backup, players_csv, results_csv, teams_csv
from ..bracket import BracketError, delete_result, save_result
from ..config_store import INVITE_KEY, get_setting, invite_code, set_setting
from ..settings import get_settings
from .account import MIN_PASSWORD
from .common import State, flash, get_state, local_dt, redirect, render

router = APIRouter()


# ------------------------------------------------------------ Ergebnisse


def _match(state: State, match_id: int) -> models.Match:
    m = state.db.get(models.Match, match_id)
    if m is None or m.season_id != state.season.id:
        raise HTTPException(404)
    return m


@router.get("/bracket/match/{match_id}")
def result_form(match_id: int, request: Request, state: State = Depends(get_state),
                admin: models.User = Depends(require_admin)):
    m = _match(state, match_id)
    if m.p1_id is None or m.p2_id is None:
        flash(request, "Both players of this match are not known yet.", "error")
        return redirect(f"/matches/{m.id}")
    return render(request, "result_form.html", state, m=m)


@router.post("/bracket/match/{match_id}")
async def result_save(match_id: int, request: Request, state: State = Depends(get_state),
                      admin: models.User = Depends(require_admin)):
    m = _match(state, match_id)
    form = await request.form()

    def num(key: str) -> int:
        try:
            return max(0, int(form.get(key) or 0))
        except ValueError:
            return 0

    keys = [s.key for s in state.rules.scoring.stats]
    try:
        save_result(
            state.db, state.rules, m,
            num("sets_p1"), num("sets_p2"),
            {k: num(f"p1_{k}") for k in keys},
            {k: num(f"p2_{k}") for k in keys},
        )
    except BracketError as e:
        state.db.rollback()
        flash(request, str(e), "error")
        return redirect(f"/bracket/match/{m.id}")
    flash(request, "Result saved.")
    return redirect(f"/bracket?section={state.bracket.section_of_match(m)}")


@router.post("/bracket/match/{match_id}/delete")
def result_delete(match_id: int, request: Request, state: State = Depends(get_state),
                  admin: models.User = Depends(require_admin)):
    m = _match(state, match_id)
    try:
        delete_result(state.db, m)
        flash(request, "Result deleted.")
    except BracketError as e:
        state.db.rollback()
        flash(request, str(e), "error")
    return redirect(f"/matches/{m.id}")


# ------------------------------------------------------------ Admin-Seite


def _invite_lists(state: State) -> tuple[list[models.Invite], list[models.Invite]]:
    invites = state.db.scalars(select(models.Invite).order_by(models.Invite.created_at.desc(),
                                                              models.Invite.id.desc())).all()
    open_ = [i for i in invites if i.used_at is None]
    used = sorted((i for i in invites if i.used_at), key=lambda i: i.used_at, reverse=True)
    return open_, used


@router.get("/admin")
def admin_page(request: Request, state: State = Depends(get_state), admin: models.User = Depends(require_admin)):
    users = state.db.scalars(select(models.User).order_by(func.lower(models.User.username))).all()
    with_team = {t.user_id for t in state.active_teams}
    total = sum(state.rules.matches_in_round(r) for r in range(1, state.rules.tournament.num_rounds + 1))
    open_invites, _ = _invite_lists(state)
    lock_at = state.rules.lock_at
    now = datetime.now(timezone.utc)
    auto_locked = bool(lock_at) and state.locked and not state.season.teams_locked
    return render(
        request, "admin.html", state,
        n_users=len(users),
        n_teams=len(state.active_teams),
        without_team=[u.username for u in users if u.id not in with_team],
        total_matches=total,
        played=sum(1 for m in state.matches if m.is_played),
        scheduled=sum(1 for m in state.matches if m.scheduled_at),
        # Laut Spielplan schon angefangen, aber noch kein Ergebnis eingetragen
        waiting=sum(1 for m in state.matches
                    if m.scheduled_at and local_dt(m.scheduled_at) <= now and not m.is_played),
        n_open_invites=len(open_invites),
        auto_locked=auto_locked,
    )


@router.post("/admin/invite")
def set_invite(request: Request, action: str = Form(...), code: str = Form(""),
               state: State = Depends(get_state), admin: models.User = Depends(require_admin)):
    if action == "generate":
        set_setting(state.db, INVITE_KEY, secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8].lower())
        flash(request, "New invite code created. Old links no longer work.")
    elif action == "set":
        code = code.strip()
        if not 4 <= len(code) <= 40:
            flash(request, "Invite code must be 4-40 characters.", "error")
        else:
            set_setting(state.db, INVITE_KEY, code)
            flash(request, "Invite code saved.")
    elif action == "disable":
        set_setting(state.db, INVITE_KEY, None)
        flash(request, "Self-registration via invite code is off."
              + (" (INVITE_CODE in the environment is still active.)" if get_settings().invite_code else ""))
    return redirect("/admin/users#code")


@router.post("/admin/invites")
def create_invite(request: Request, note: str = Form(""), state: State = Depends(get_state),
                  admin: models.User = Depends(require_admin)):
    note = note.strip()
    if len(note) > 60:
        flash(request, "Note can have at most 60 characters.", "error")
    else:
        state.db.add(models.Invite(token=secrets.token_urlsafe(12), note=note))
        state.db.commit()
        flash(request, "Personal invite link created" + (f" for “{note}”." if note else "."))
    return redirect("/admin/users#invites")


@router.post("/admin/invites/{invite_id}/delete")
def delete_invite(invite_id: int, request: Request, state: State = Depends(get_state),
                  admin: models.User = Depends(require_admin)):
    inv = state.db.get(models.Invite, invite_id)
    if inv is None:
        raise HTTPException(404)
    state.db.delete(inv)
    state.db.commit()
    flash(request, "Invite link deleted." if inv.used_at is None else "Entry deleted.")
    return redirect("/admin/users#invites")


@router.get("/admin/users")
def admin_users(request: Request, state: State = Depends(get_state), admin: models.User = Depends(require_admin)):
    users = state.db.scalars(select(models.User).order_by(func.lower(models.User.username))).all()
    team_counts = dict(
        state.db.execute(
            select(models.Team.user_id, func.count())
            .where(models.Team.season_id == state.season.id)
            .group_by(models.Team.user_id)
        ).all()
    )
    open_invites, used_invites = _invite_lists(state)
    return render(request, "admin_users.html", state, users=users, team_counts=team_counts,
                  open_invites=open_invites, used_invites=used_invites,
                  invite_note={i.used_by_id: i.note for i in used_invites if i.used_by_id and i.note},
                  invite_code=invite_code(state.db),
                  invite_from_env=bool(get_settings().invite_code) and not get_setting(state.db, INVITE_KEY))


@router.post("/admin/lock")
def set_lock(request: Request, locked: bool = Form(False), state: State = Depends(get_state),
             admin: models.User = Depends(require_admin)):
    state.season.teams_locked = locked
    state.db.commit()
    flash(request, "Teams are now locked." if locked else "Teams are unlocked.")
    return redirect("/admin")


@router.post("/admin/users")
def create_user(request: Request, username: str = Form(...), password: str = Form(...),
                is_admin: bool = Form(False), state: State = Depends(get_state),
                admin: models.User = Depends(require_admin)):
    username = username.strip()
    if not username or len(username) > 40:
        flash(request, "Username must be 1-40 characters.", "error")
    elif len(password) < MIN_PASSWORD:
        flash(request, f"Password must have at least {MIN_PASSWORD} characters.", "error")
    elif state.db.scalar(select(models.User).where(func.lower(models.User.username) == username.lower())):
        flash(request, "Username already exists.", "error")
    else:
        state.db.add(models.User(username=username, password_hash=hash_password(password), is_admin=is_admin))
        state.db.commit()
        flash(request, f"User “{username}” created.")
    return redirect("/admin/users")


def _other_user(state: State, user_id: int, admin: models.User) -> models.User:
    user = state.db.get(models.User, user_id)
    if user is None:
        raise HTTPException(404)
    if user.id == admin.id:
        raise HTTPException(400, "Not possible for your own account.")
    return user


@router.post("/admin/users/{user_id}/admin")
def toggle_admin(user_id: int, request: Request, state: State = Depends(get_state),
                 admin: models.User = Depends(require_admin)):
    user = _other_user(state, user_id, admin)
    user.is_admin = not user.is_admin
    state.db.commit()
    flash(request, f"“{user.username}” is {'now' if user.is_admin else 'no longer'} an admin.")
    return redirect("/admin/users")


@router.post("/admin/users/{user_id}/password")
def reset_password(user_id: int, request: Request, password: str = Form(...),
                   state: State = Depends(get_state), admin: models.User = Depends(require_admin)):
    user = state.db.get(models.User, user_id)
    if user is None:
        raise HTTPException(404)
    if len(password) < MIN_PASSWORD:
        flash(request, f"Password must have at least {MIN_PASSWORD} characters.", "error")
    else:
        user.password_hash = hash_password(password)
        state.db.commit()
        flash(request, f"Password for “{user.username}” changed.")
    return redirect("/admin/users")


@router.post("/admin/users/{user_id}/avatar/delete")
def delete_user_avatar(user_id: int, request: Request, state: State = Depends(get_state),
                       admin: models.User = Depends(require_admin)):
    user = state.db.get(models.User, user_id)
    if user is None:
        raise HTTPException(404)
    delete_avatar(state.db, user)
    flash(request, f"Profile picture of “{user.username}” removed.")
    return redirect("/admin/users")


@router.post("/admin/users/{user_id}/delete")
def delete_user(user_id: int, request: Request, state: State = Depends(get_state),
                admin: models.User = Depends(require_admin)):
    user = _other_user(state, user_id, admin)
    name = user.username
    state.db.delete(user)
    state.db.commit()
    flash(request, f"User “{name}” and their teams deleted.")
    return redirect("/admin/users")


# ------------------------------------------------------------ Export & Backup

_CSV_EXPORTS = {"teams": teams_csv, "results": results_csv, "players": players_csv}


@router.get("/admin/export/{kind}")
def export(kind: str, state: State = Depends(get_state), admin: models.User = Depends(require_admin)):
    stamp = f"{state.season.key}_{date.today().isoformat()}"
    if kind == "backup":
        body = json.dumps(export_backup(state.db, state.season), ensure_ascii=False, indent=1)
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="fantasy-darts_backup_{stamp}.json"'})
    if kind not in _CSV_EXPORTS:
        raise HTTPException(404)
    body = _CSV_EXPORTS[kind](state.db, state.season, state.rules)
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="fantasy-darts_{kind}_{stamp}.csv"'})
