"""Admin: Spieler anlegen/bearbeiten und in der Auslosung ersetzen."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from .. import models
from ..auth import require_admin
from ..flags import COUNTRY_CODES
from .common import State, flash, get_state, redirect, render

router = APIRouter(prefix="/fantasy/admin/players")


def _player(state: State, player_id: int) -> models.Player:
    p = state.players.get(player_id)
    if p is None:
        raise HTTPException(404)
    return p


def _r1_match(state: State, player_id: int) -> models.Match | None:
    return next((m for m in state.matches if m.round == 1 and player_id in (m.p1_id, m.p2_id)), None)


async def _read(request: Request) -> tuple[dict, list[str]]:
    form = await request.form()
    errors = []
    name = str(form.get("name", "")).strip()
    nation = str(form.get("nation", "")).strip()
    if not name or len(name) > 80:
        errors.append("Name must be 1-80 characters.")
    try:
        price = round(float(str(form.get("price", "")).replace(",", ".")), 1)
        if price <= 0:
            raise ValueError
    except ValueError:
        price = None
        errors.append("Price must be a positive number (e.g. 12.5).")
    seed_raw = str(form.get("seed", "")).strip()
    seed = None
    if seed_raw:
        try:
            seed = int(seed_raw)
            if seed < 1:
                raise ValueError
        except ValueError:
            errors.append("Seed must be empty or a whole number ≥ 1.")
    return {"name": name, "nation": nation, "price": price, "seed": seed}, errors


def _name_taken(state: State, name: str, exclude: int | None = None) -> bool:
    q = select(models.Player.id).where(models.Player.season_id == state.season.id,
                                       func.lower(models.Player.name) == name.lower())
    if exclude is not None:
        q = q.where(models.Player.id != exclude)
    return state.db.scalar(q) is not None


def _teams_with(state: State, player_id: int) -> int:
    return state.db.scalar(select(func.count()).select_from(models.TeamPlayer)
                           .join(models.Team, models.Team.id == models.TeamPlayer.team_id)
                           .where(models.Team.season_id == state.season.id,
                                  models.TeamPlayer.player_id == player_id)) or 0


def _form(request, state, p, data=None, errors=(), status_code=200):
    in_draw = {pid for m in state.matches if m.round == 1 for pid in (m.p1_id, m.p2_id)}
    r1 = _r1_match(state, p.id) if p else None
    replacements = sorted((x for x in state.players.values() if x.id not in in_draw), key=lambda x: x.name)
    return render(request, "admin_player_form.html", state, p=p, data=data or (
        {"name": p.name, "nation": p.nation, "price": p.price, "seed": p.seed} if p else
        {"name": "", "nation": "", "price": "", "seed": None}),
        errors=list(errors), nations=sorted(COUNTRY_CODES), r1=r1, replacements=replacements,
        n_teams=_teams_with(state, p.id) if p else 0, status_code=status_code)


@router.get("")
def players_admin(request: Request, state: State = Depends(get_state), admin: models.User = Depends(require_admin)):
    in_draw = {pid for m in state.matches if m.round == 1 for pid in (m.p1_id, m.p2_id)}
    rows = sorted(state.players.values(), key=lambda p: (p.seed is None, p.seed or 0, p.name))
    return render(request, "admin_players.html", state, rows=rows, in_draw=in_draw)


@router.get("/new")
def new_form(request: Request, state: State = Depends(get_state), admin: models.User = Depends(require_admin)):
    return _form(request, state, None)


@router.post("/new")
async def create(request: Request, state: State = Depends(get_state), admin: models.User = Depends(require_admin)):
    data, errors = await _read(request)
    if data["name"] and _name_taken(state, data["name"]):
        errors.append("A player with this name already exists.")
    if errors:
        return _form(request, state, None, data, errors, 400)
    p = models.Player(season_id=state.season.id, **data)
    state.db.add(p)
    state.db.commit()
    flash(request, f"Player “{p.name}” created. To put them into the draw, open a player in the draw and replace them.")
    return redirect("/fantasy/admin/players")


@router.get("/{player_id}")
def edit_form(player_id: int, request: Request, state: State = Depends(get_state),
              admin: models.User = Depends(require_admin)):
    return _form(request, state, _player(state, player_id))


@router.post("/{player_id}")
async def update(player_id: int, request: Request, state: State = Depends(get_state),
                 admin: models.User = Depends(require_admin)):
    p = _player(state, player_id)
    data, errors = await _read(request)
    if data["name"] and _name_taken(state, data["name"], exclude=p.id):
        errors.append("A player with this name already exists.")
    if data["price"] is not None and abs(data["price"] - p.price) > 1e-9 and state.locked:
        errors.append("Prices can't change while teams are locked – budgets were checked against the old price.")
    if errors:
        return _form(request, state, p, data, errors, 400)
    for k, v in data.items():
        setattr(p, k, v)
    state.db.commit()
    flash(request, f"“{p.name}” saved.")
    return redirect("/fantasy/admin/players")


@router.post("/{player_id}/replace")
async def replace_in_draw(player_id: int, request: Request, state: State = Depends(get_state),
                          admin: models.User = Depends(require_admin)):
    """Spieler zieht zurück -> Nachrücker übernimmt seinen Platz in Runde 1."""
    p = _player(state, player_id)
    form = await request.form()
    try:
        new = _player(state, int(form.get("replacement_id") or 0))
    except (HTTPException, ValueError):
        flash(request, "Choose a replacement player.", "error")
        return redirect(f"/fantasy/admin/players/{p.id}")
    m = _r1_match(state, p.id)
    in_draw = {pid for x in state.matches if x.round == 1 for pid in (x.p1_id, x.p2_id)}
    if m is None:
        flash(request, f"{p.name} is not in the draw.", "error")
    elif m.is_played:
        flash(request, "This first-round match already has a result.", "error")
    elif new.id in in_draw:
        flash(request, f"{new.name} is already in the draw.", "error")
    else:
        if m.p1_id == p.id:
            m.p1_id = new.id
        else:
            m.p2_id = new.id
        state.db.commit()
        n = _teams_with(state, p.id)
        flash(request, f"{new.name} replaces {p.name} in the draw."
              + (f" {n} team(s) still have {p.name} and will get no points for them." if n else ""))
    return redirect("/fantasy/admin/players")
