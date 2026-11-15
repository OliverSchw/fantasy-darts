"""Eigene Teams: anlegen, bearbeiten, aktivieren, löschen."""

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import models
from ..flags import flag_code
from ..auth import require_user
from ..teams import TeamInput, activate_team, delete_team, name_taken, save_team, user_teams, validate_team
from .common import State, flash, get_state, redirect, render

router = APIRouter(prefix="/my")


def _own_team(state: State, team_id: int, user: models.User) -> models.Team:
    team = state.db.get(models.Team, team_id)
    if team is None or team.season_id != state.season.id or team.user_id != user.id:
        raise HTTPException(404)
    return team


def _ensure_unlocked(request: Request, state: State):
    if state.locked:
        flash(request, "Teams are locked - no more changes possible.", "error")
        return redirect("/my")
    return None


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _read_form(request: Request) -> TeamInput:
    form = await request.form()
    return TeamInput(
        name=str(form.get("name", "")),
        player_ids=[i for i in (_int_or_none(v) for v in form.getlist("player_ids")) if i is not None],
        playmaker_id=_int_or_none(form.get("playmaker_id")),
        underdog_id=_int_or_none(form.get("underdog_id")),
        champion_pick_id=_int_or_none(form.get("champion_pick_id")),
    )


def _builder(request: Request, state: State, team: models.Team | None, data: TeamInput | None, errors=()):
    if data is None and team is not None:
        data = TeamInput(team.name, team.player_ids, team.playmaker_id, team.underdog_id, team.champion_pick_id)
    players = sorted(state.players.values(), key=lambda p: (-p.price, p.name))
    players_json = [
        {"id": p.id, "name": p.name, "nation": p.nation, "flag": flag_code(p.nation), "price": p.price, "seed": p.seed}
        for p in players
    ]
    initial = {
        "name": data.name if data else "",
        "selected": data.player_ids if data else [],
        "playmaker": data.playmaker_id if data else None,
        "underdog": data.underdog_id if data else None,
        "champion": data.champion_pick_id if data else None,
    }
    return render(request, "team_builder.html", state, team=team, players_json=players_json,
                  initial=initial, errors=list(errors), status_code=400 if errors else 200)


@router.get("")
def my_teams(request: Request, state: State = Depends(get_state), user: models.User = Depends(require_user)):
    teams = user_teams(state.db, state.season.id, user.id)
    scores = {t.id: state.team_score(t).total for t in teams}
    return render(request, "my_teams.html", state, teams=teams, scores=scores)


@router.get("/new")
def new_team_form(request: Request, state: State = Depends(get_state), user: models.User = Depends(require_user),
                  copy: int | None = None):
    if (r := _ensure_unlocked(request, state)) is not None:
        return r
    if len(user_teams(state.db, state.season.id, user.id)) >= state.rules.team.max_teams_per_user:
        flash(request, f"You can have at most {state.rules.team.max_teams_per_user} teams.", "error")
        return redirect("/my")
    data = None
    if copy is not None:  # eigenes Team als Vorlage
        src = _own_team(state, copy, user)
        data = TeamInput(f"{src.name} (copy)"[:40], src.player_ids, src.playmaker_id, src.underdog_id,
                         src.champion_pick_id)
    return _builder(request, state, None, data)


@router.post("/new")
async def create_team(request: Request, state: State = Depends(get_state), user: models.User = Depends(require_user)):
    if (r := _ensure_unlocked(request, state)) is not None:
        return r
    data = await _read_form(request)
    errors = validate_team(state.rules, data, state.players)
    if len(user_teams(state.db, state.season.id, user.id)) >= state.rules.team.max_teams_per_user:
        errors.append(f"You can have at most {state.rules.team.max_teams_per_user} teams.")
    if data.name.strip() and name_taken(state.db, state.season.id, data.name):
        errors.append("This team name is already taken.")
    if errors:
        return _builder(request, state, None, data, errors)
    team = save_team(state.db, models.Team(season_id=state.season.id, user_id=user.id), data)
    flash(request, f"Team “{team.name}” created." + (" It is your active team." if team.is_active else ""))
    return redirect("/my")


@router.get("/{team_id}/edit")
def edit_team_form(team_id: int, request: Request, state: State = Depends(get_state),
                   user: models.User = Depends(require_user)):
    team = _own_team(state, team_id, user)
    if (r := _ensure_unlocked(request, state)) is not None:
        return r
    return _builder(request, state, team, None)


@router.post("/{team_id}/edit")
async def update_team(team_id: int, request: Request, state: State = Depends(get_state),
                      user: models.User = Depends(require_user)):
    team = _own_team(state, team_id, user)
    if (r := _ensure_unlocked(request, state)) is not None:
        return r
    data = await _read_form(request)
    errors = validate_team(state.rules, data, state.players)
    if data.name.strip() and name_taken(state.db, state.season.id, data.name, exclude_team_id=team.id):
        errors.append("This team name is already taken.")
    if errors:
        return _builder(request, state, team, data, errors)
    save_team(state.db, team, data)
    flash(request, f"Team “{team.name}” saved.")
    return redirect("/my")


@router.post("/{team_id}/activate")
def activate(team_id: int, request: Request, state: State = Depends(get_state),
             user: models.User = Depends(require_user)):
    team = _own_team(state, team_id, user)
    if (r := _ensure_unlocked(request, state)) is not None:
        return r
    activate_team(state.db, team)
    flash(request, f"“{team.name}” is now your active team.")
    return redirect("/my")


@router.post("/{team_id}/delete")
def delete(team_id: int, request: Request, state: State = Depends(get_state),
           user: models.User = Depends(require_user)):
    team = _own_team(state, team_id, user)
    if (r := _ensure_unlocked(request, state)) is not None:
        return r
    name = team.name
    delete_team(state.db, team)
    flash(request, f"Team “{name}” deleted.")
    return redirect("/my")
