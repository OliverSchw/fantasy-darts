"""Admin: Spielregeln & Punkte in der Oberfläche bearbeiten (statt in rules.toml)."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy import select

from .. import models
from ..auth import require_admin
from ..config_store import reset_rules, rules_customized, save_rules
from ..rules import Rules
from ..settings import get_settings
from ..teams import TeamInput, validate_team
from .common import State, flash, get_state, redirect, render

router = APIRouter(prefix="/fantasy/admin/rules")


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def _local_input(dt: datetime | None) -> str:
    return dt.astimezone(_tz()).strftime("%Y-%m-%dT%H:%M") if dt else ""


def _num(form, key: str, errors: list[str], label: str, integer: bool = False):
    raw = str(form.get(key, "")).strip().replace(",", ".")
    try:
        value = float(raw)
        if integer:
            if value != int(value):
                raise ValueError
            return int(value)
        return value
    except ValueError:
        errors.append(f"{label}: please enter a {'whole ' if integer else ''}number.")
        return 0


def _slug(label: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:30] or "stat"
    if base[0].isdigit():
        base = "s" + base
    key, i = base, 2
    while key in taken:
        key, i = f"{base}_{i}", i + 1
    return key


def parse_rules_form(form, current: Rules) -> tuple[dict, list[str]]:
    """Formular -> Regel-Dict (noch nicht validiert) + Eingabefehler."""
    e: list[str] = []
    n = current.tournament.num_rounds
    lock_raw = str(form.get("lock_at", "")).strip()
    lock_at = None
    if lock_raw:
        try:
            lock_at = datetime.fromisoformat(lock_raw).replace(tzinfo=_tz()).isoformat()
        except ValueError:
            e.append("Lock time: invalid date.")

    stats, keys = [], set()
    for i in range(len(current.scoring.stats)):
        key = str(form.get(f"stat_key_{i}", ""))
        if form.get(f"stat_delete_{i}") or not key:
            continue
        label = str(form.get(f"stat_label_{i}", "")).strip() or key
        stats.append({"key": key, "label": label, "points": _num(form, f"stat_points_{i}", e, label)})
        keys.add(key)
    new_label = str(form.get("new_stat_label", "")).strip()
    if new_label:
        stats.append({"key": _slug(new_label, keys), "label": new_label,
                      "points": _num(form, "new_stat_points", e, new_label)})

    data = {
        "name": str(form.get("name", "")).strip() or current.name,
        "lock_at": lock_at,
        "team": {
            "budget": _num(form, "budget", e, "Budget"),
            "squad_size": _num(form, "squad_size", e, "Players per team", integer=True),
            "max_teams_per_user": _num(form, "max_teams_per_user", e, "Teams per user", integer=True),
            "playmaker": {"label": str(form.get("pm_label", "")).strip() or "Playmaker",
                          "max_price": _num(form, "pm_max_price", e, "Playmaker max price"),
                          "multiplier": _num(form, "pm_multiplier", e, "Playmaker multiplier")},
            "underdog": {"label": str(form.get("ud_label", "")).strip() or "Underdog",
                         "max_price": _num(form, "ud_max_price", e, "Underdog max price"),
                         "multiplier": _num(form, "ud_multiplier", e, "Underdog multiplier")},
            "champion_pick": {"bonus": _num(form, "champion_bonus", e, "Champion pick bonus")},
        },
        "tournament": {
            "round_names": [str(form.get(f"round_name_{r}", "")).strip() or current.tournament.round_names[r]
                            for r in range(n)],
            "sets_to_win": [_num(form, f"sets_to_win_{r}", e, f"Sets to win ({current.tournament.round_names[r]})",
                                 integer=True) for r in range(n)],
        },
        "scoring": {
            "per_set_won": _num(form, "per_set_won", e, "Points per set won"),
            "per_set_margin_winner": _num(form, "per_set_margin_winner", e, "Points per set of margin"),
            "round_win_bonus": [_num(form, f"round_bonus_{r}", e, f"Win bonus ({current.tournament.round_names[r]})")
                                for r in range(n)],
            "stats": stats,
        },
    }
    if data["team"]["squad_size"] < 1:
        e.append("Players per team must be at least 1.")
    if data["team"]["max_teams_per_user"] < 1:
        e.append("Teams per user must be at least 1.")
    if any(s < 1 for s in data["tournament"]["sets_to_win"]):
        e.append("Sets to win must be at least 1 in every round.")
    for mult in (data["team"]["playmaker"]["multiplier"], data["team"]["underdog"]["multiplier"]):
        if mult < 1:
            e.append("Multipliers must be at least 1.")
    return data, e


def _invalid_teams(state: State, rules: Rules) -> list[models.Team]:
    teams = state.db.scalars(select(models.Team).where(models.Team.season_id == state.season.id)).all()
    return [t for t in teams if validate_team(rules, TeamInput(t.name, t.player_ids, t.playmaker_id,
                                                               t.underdog_id, t.champion_pick_id), state.players)]


def _page(request, state, rules: Rules, errors=(), status_code=200):
    return render(request, "admin_rules.html", state, r=rules, errors=list(errors), status_code=status_code,
                  lock_input=_local_input(rules.lock_at), custom=rules_customized(state.db, state.season),
                  tz=get_settings().timezone)


@router.get("")
def rules_form(request: Request, state: State = Depends(get_state), admin: models.User = Depends(require_admin)):
    return _page(request, state, state.rules)


@router.post("")
async def rules_save(request: Request, state: State = Depends(get_state), admin: models.User = Depends(require_admin)):
    if state.locked:
        flash(request, "Teams are locked – unlock them first if you really want to change the rules.", "error")
        return redirect("/fantasy/admin/rules")
    data, errors = parse_rules_form(await request.form(), state.rules)
    if not errors:
        try:
            new_rules = Rules.model_validate(data)
        except ValidationError as ex:
            errors = [err["msg"].removeprefix("Value error, ") for err in ex.errors()]
    if errors:
        # Eingaben behalten, damit nichts verloren geht
        try:
            shown = Rules.model_validate(data)
        except ValidationError:
            shown = state.rules
        return _page(request, state, shown, errors, 400)

    save_rules(state.db, state.season, new_rules)
    invalid = _invalid_teams(state, new_rules)
    flash(request, "Rules saved. Points are recalculated automatically.")
    if invalid:
        names = ", ".join(t.name for t in invalid[:5]) + (" …" if len(invalid) > 5 else "")
        flash(request, f"{len(invalid)} team(s) no longer fit the new rules (e.g. budget or squad size): {names}. "
                       "Their owners need to edit them before the lock.", "error")
    return redirect("/fantasy/admin/rules")


@router.post("/reset")
def rules_reset(request: Request, state: State = Depends(get_state), admin: models.User = Depends(require_admin)):
    if state.locked:
        flash(request, "Teams are locked – unlock them first.", "error")
    else:
        reset_rules(state.db, state.season)
        flash(request, "Rules reset to the season defaults (rules.toml).")
    return redirect("/fantasy/admin/rules")
