"""Fantasy Darts – Admin: Ergebnisse eintragen, Übersicht, Teams sperren, Export."""

import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, select

from .. import models
from ..auth import require_admin
from ..backup import export_backup, players_csv, results_csv, teams_csv
from ..bracket import BracketError, delete_result, save_result
from .common import State, flash, get_state, local_dt, redirect, render
from .members import _invite_lists

router = APIRouter()


# ------------------------------------------------------------ Ergebnisse


def _match(state: State, match_id: int) -> models.Match:
    m = state.db.get(models.Match, match_id)
    if m is None or m.season_id != state.season.id:
        raise HTTPException(404)
    return m


@router.get("/fantasy/bracket/match/{match_id}")
def result_form(match_id: int, request: Request, state: State = Depends(get_state),
                admin: models.User = Depends(require_admin)):
    m = _match(state, match_id)
    if m.p1_id is None or m.p2_id is None:
        flash(request, "Both players of this match are not known yet.", "error")
        return redirect(f"/fantasy/matches/{m.id}")
    return render(request, "result_form.html", state, m=m)


@router.post("/fantasy/bracket/match/{match_id}")
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
        return redirect(f"/fantasy/bracket/match/{m.id}")
    flash(request, "Result saved.")
    return redirect(f"/fantasy/bracket?section={state.bracket.section_of_match(m)}")


@router.post("/fantasy/bracket/match/{match_id}/delete")
def result_delete(match_id: int, request: Request, state: State = Depends(get_state),
                  admin: models.User = Depends(require_admin)):
    m = _match(state, match_id)
    try:
        delete_result(state.db, m)
        flash(request, "Result deleted.")
    except BracketError as e:
        state.db.rollback()
        flash(request, str(e), "error")
    return redirect(f"/fantasy/matches/{m.id}")


# ------------------------------------------------------------ Admin-Seite


@router.get("/fantasy/admin")
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


@router.post("/fantasy/admin/lock")
def set_lock(request: Request, locked: bool = Form(False), state: State = Depends(get_state),
             admin: models.User = Depends(require_admin)):
    state.season.teams_locked = locked
    state.db.commit()
    flash(request, "Teams are now locked." if locked else "Teams are unlocked.")
    return redirect("/fantasy/admin")


# ------------------------------------------------------------ Export & Backup

_CSV_EXPORTS = {"teams": teams_csv, "results": results_csv, "players": players_csv}


@router.get("/fantasy/admin/export/{kind}")
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
