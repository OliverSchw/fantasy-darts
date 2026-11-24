"""Admin: Anstoßzeiten der Matches eintragen (auch für spätere Runden mit noch offenen Paarungen)."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request

from .. import models
from ..auth import require_admin
from ..settings import get_settings
from .common import State, flash, get_state, local_dt, redirect, render

router = APIRouter(prefix="/fantasy/admin/schedule")


def _round(state: State, round: int | None) -> int:
    n = state.rules.tournament.num_rounds
    if round and 1 <= round <= n:
        return round
    # erste Runde, in der noch nicht alles angesetzt ist
    return next((m.round for m in state.matches if not m.scheduled_at and not m.is_played), 1)


@router.get("")
def schedule_form(request: Request, state: State = Depends(get_state), admin: models.User = Depends(require_admin),
                  round: int | None = None):
    rnd = _round(state, round)
    matches = [state.bracket.view(m) for m in state.matches if m.round == rnd]
    values = {mv.match.id: (local_dt(mv.match.scheduled_at).strftime("%Y-%m-%dT%H:%M")
                            if mv.match.scheduled_at else "") for mv in matches}
    counts = {r: sum(1 for m in state.matches if m.round == r and m.scheduled_at)
              for r in range(1, state.rules.tournament.num_rounds + 1)}
    return render(request, "admin_schedule.html", state, rnd=rnd, matches=matches, values=values, counts=counts,
                  tz=get_settings().timezone)


@router.post("")
async def schedule_save(request: Request, state: State = Depends(get_state),
                        admin: models.User = Depends(require_admin), round: int | None = None):
    rnd = _round(state, round)
    form = await request.form()
    tz = ZoneInfo(get_settings().timezone)
    changed, errors = 0, 0
    for m in state.matches:
        if m.round != rnd or f"time_{m.id}" not in form:
            continue
        raw = str(form.get(f"time_{m.id}", "")).strip()
        try:
            # immer als UTC speichern: SQLite verliert sonst die Zeitzone
            new = datetime.fromisoformat(raw).replace(tzinfo=tz).astimezone(timezone.utc) if raw else None
        except ValueError:
            errors += 1
            continue
        old = local_dt(m.scheduled_at)
        if (old is None) != (new is None) or (old is not None and new is not None and old != new):
            m.scheduled_at = new
            changed += 1
    state.db.commit()
    flash(request, f"{changed} match time(s) saved." if changed else "Nothing changed.")
    if errors:
        flash(request, f"{errors} invalid date(s) ignored.", "error")
    return redirect(f"/fantasy/admin/schedule?round={rnd}")
