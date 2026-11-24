"""Bierpong-Bereich: Spiele live zählen, Turniere, Stats. Nur für eingeloggte Mitglieder."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import beerpong as bp
from .. import competitors
from .. import models
from .. import tournaments as tour
from ..auth import require_user
from ..competitors import CompetitorError
from ..db import get_db
from .common import flash, redirect, render

router = APIRouter(prefix="/beerpong")
ERRORS = (bp.BeerpongError, CompetitorError, tour.TournamentError)


def _game(db: Session, game_id: int) -> models.BeerpongGame:
    g = db.get(models.BeerpongGame, game_id)
    if g is None:
        raise HTTPException(404)
    return g


def _games(db: Session, limit: int, status: str | None = None):
    q = select(models.BeerpongGame).where(models.BeerpongGame.status != "abandoned")
    if status:
        q = q.where(models.BeerpongGame.status == status)
    return db.scalars(q.order_by(models.BeerpongGame.created_at.desc(), models.BeerpongGame.id.desc()).limit(limit)).all()


def _read_team(form, prefix: str, db: Session) -> list[int]:
    ids = []
    for i in range(4):
        raw = str(form.get(f"{prefix}{i}", "")).strip()
        guest = str(form.get(f"{prefix}g{i}", "")).strip()
        if raw == "guest" and guest:
            ids.append(competitors.create_guest(db, guest).id)
        elif raw.isdigit():
            ids.append(int(raw))
    return ids


# ---------------------------------------------------------------- Übersicht & Spiele


@router.get("")
def bp_home(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    me = competitors.competitor_for_user(db, user)
    return render(request, "beerpong/home.html", user=user, me=me, my_stats=bp.compute_stats(db, [me.id]).get(me.id),
                  live=_games(db, 20, "live"), recent=_games(db, 8, "finished"))


@router.get("/new")
def bp_new_form(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    me = competitors.competitor_for_user(db, user)
    return render(request, "beerpong/new.html", user=user, competitors=competitors.all_competitors(db),
                  cup_options=bp.CUP_OPTIONS, form={"cups": 10, "t1": [me.id], "t2": [], "n1": "", "n2": ""})


@router.post("/new")
async def bp_new(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    form = await request.form()
    keep = {"cups": int(form.get("cups") or 10) if str(form.get("cups", "")).isdigit() else 10,
            "t1": [], "t2": [], "n1": str(form.get("n1", "")).strip()[:60], "n2": str(form.get("n2", "")).strip()[:60]}
    try:
        keep["t1"] = _read_team(form, "a", db)
        keep["t2"] = _read_team(form, "b", db)
        game = bp.create_game(db, keep["cups"], keep["t1"], keep["t2"], user, names=(keep["n1"] or None, keep["n2"] or None))
    except ERRORS as e:
        db.rollback()
        return render(request, "beerpong/new.html", status_code=400, user=user, error=str(e),
                      competitors=competitors.all_competitors(db), cup_options=bp.CUP_OPTIONS, form=keep)
    return redirect(f"/beerpong/games/{game.id}")


@router.get("/games/{game_id}")
def bp_game(game_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    g = _game(db, game_id)
    t, tm = bp._tournament_of(db, g)
    return render(request, "beerpong/game.html", user=user, g=g, can_manage=bp.can_manage(user, g),
                  tinfo={"t": t, "title": tour.round_title(tm.round, t.num_rounds)} if t else None)


@router.get("/games/{game_id}/version")
def bp_version(game_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    g = _game(db, game_id)
    return JSONResponse({"v": g.version, "status": g.status}, headers={"Cache-Control": "no-store"})


@router.post("/games/{game_id}/hit")
async def bp_hit(game_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    g = _game(db, game_id)
    if not bp.can_manage(user, g):
        raise HTTPException(403, "Only the players and whoever started the game can count.")
    form = await request.form()
    try:
        bp.add_hit(db, g, int(form.get("side", 0)), int(form.get("delta", 0)), int(form.get("v", -1)))
        if g.status == "finished":
            flash(request, f"🍺 Winner: {g.team_name(g.winner_side)} ({max(g.hits1, g.hits2)}:{min(g.hits1, g.hits2)})")
    except ValueError as e:
        db.rollback()
        flash(request, str(e) if isinstance(e, ERRORS) else "Invalid input.", "error")
    return redirect(f"/beerpong/games/{g.id}")


@router.post("/games/{game_id}/abandon")
def bp_abandon(game_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    g = _game(db, game_id)
    if not bp.can_manage(user, g):
        raise HTTPException(403)
    try:
        bp.abandon(db, g)
        flash(request, "Game abandoned – it doesn't count for the stats.")
    except ERRORS as e:
        db.rollback()
        flash(request, str(e), "error")
        return redirect(f"/beerpong/games/{g.id}")
    return redirect("/beerpong")


@router.get("/stats")
def bp_stats(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    stats = bp.compute_stats(db)
    rows = [(c, stats[c.id]) for c in competitors.all_competitors(db) if c.id in stats]
    rows.sort(key=lambda r: (-(r[1].win_pct or 0), -r[1].games))
    return render(request, "beerpong/stats.html", user=user, rows=rows)


# ---------------------------------------------------------------- Turniere


def _tournament(db: Session, tid: int) -> models.Tournament:
    t = db.get(models.Tournament, tid)
    if t is None or t.sport != "beerpong":
        raise HTTPException(404)
    return t


def _tmatch(t: models.Tournament, mid: int) -> models.TournamentMatch:
    tm = next((m for m in t.matches if m.id == mid), None)
    if tm is None:
        raise HTTPException(404)
    return tm


@router.get("/tournaments")
def bp_tournaments(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    ts = db.scalars(select(models.Tournament).where(models.Tournament.sport == "beerpong")
                    .order_by(models.Tournament.created_at.desc(), models.Tournament.id.desc())).all()
    return render(request, "beerpong/tournaments.html", user=user, tournaments=ts, entry_by_id=tour.entry_by_id)


@router.get("/tournaments/new")
def bp_tournament_form(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    return render(request, "beerpong/tournament_new.html", user=user, competitors=competitors.all_competitors(db),
                  cup_options=bp.CUP_OPTIONS,
                  form={"name": "", "cups": 10, "mode": "random", "players": [], "guests": "", "teams": "", "shuffle": True})


@router.post("/tournaments/new")
async def bp_tournament_new(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    form = await request.form()
    keep = {"name": str(form.get("name", "")), "cups": int(form.get("cups") or 10) if str(form.get("cups", "")).isdigit() else 10,
            "mode": "fixed" if form.get("mode") == "fixed" else "random",
            "players": [int(x) for x in form.getlist("players") if str(x).isdigit()],
            "guests": str(form.get("guests", "")), "teams": str(form.get("teams", "")), "shuffle": bool(form.get("shuffle"))}
    try:
        if keep["cups"] not in bp.CUP_OPTIONS:
            raise bp.BeerpongError("Play with 6 or 10 cups.")
        if keep["mode"] == "fixed":
            teams, names = bp.parse_teams(db, keep["teams"])
        else:
            ids = list(keep["players"])
            for name in [g.strip() for g in keep["guests"].replace(",", "\n").splitlines() if g.strip()]:
                ids.append(competitors.create_guest(db, name).id)
            teams, names = bp.random_pairs(ids), None
        t = tour.create_tournament(db, "beerpong", keep["name"], teams, {"cups": keep["cups"]}, user,
                                   shuffle=keep["shuffle"], entry_names=names)
    except ERRORS as e:
        db.rollback()
        return render(request, "beerpong/tournament_new.html", status_code=400, user=user, error=str(e),
                      competitors=competitors.all_competitors(db), cup_options=bp.CUP_OPTIONS, form=keep)
    flash(request, f"Tournament “{t.name}” is on – {len(t.entries)} teams.")
    return redirect(f"/beerpong/tournaments/{t.id}")


@router.get("/tournaments/{tid}")
def bp_tournament(tid: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    t = _tournament(db, tid)
    live = {g.tournament_match_id: g for g in db.scalars(select(models.BeerpongGame).where(
        models.BeerpongGame.tournament_match_id.in_([m.id for m in t.matches]), models.BeerpongGame.status == "live"))}
    return render(request, "beerpong/tournament.html", user=user, t=t, cols=tour.columns(t), live=live,
                  winner=tour.entry_by_id(t, t.winner_entry_id), organizer=tour.can_organize(user, t))


@router.get("/tournaments/{tid}/matches/{mid}")
def bp_tmatch(tid: int, mid: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    t = _tournament(db, tid)
    tm = _tmatch(t, mid)
    return render(request, "beerpong/tournament_match.html", user=user, t=t, tm=tm, cups=int(t.settings.get("cups", 10)),
                  title=tour.round_title(tm.round, t.num_rounds), game=bp.tournament_game(db, tm),
                  organizer=tour.can_organize(user, t), changeable=tour.can_change(t, tm))


@router.post("/tournaments/{tid}/matches/{mid}/play")
def bp_tmatch_play(tid: int, mid: int, request: Request, db: Session = Depends(get_db),
                   user: models.User = Depends(require_user)):
    t = _tournament(db, tid)
    tm = _tmatch(t, mid)
    players = {c.user_id for e in (tm.entry1, tm.entry2) if e for c in e.competitors}
    if not (tour.can_organize(user, t) or user.id in players):
        raise HTTPException(403, "Only the organizer and the players of this match can start it.")
    try:
        game = bp.start_tournament_game(db, t, tm, user)
    except ERRORS as e:
        db.rollback()
        flash(request, str(e), "error")
        return redirect(f"/beerpong/tournaments/{t.id}/matches/{tm.id}")
    return redirect(f"/beerpong/games/{game.id}")


@router.post("/tournaments/{tid}/matches/{mid}/result")
async def bp_tmatch_result(tid: int, mid: int, request: Request, db: Session = Depends(get_db),
                           user: models.User = Depends(require_user)):
    t = _tournament(db, tid)
    tm = _tmatch(t, mid)
    if not tour.can_organize(user, t):
        raise HTTPException(403)
    form = await request.form()
    try:
        bp.record_tournament_result(db, t, tm, int(form.get("score1", -1)), int(form.get("score2", -1)), user)
        flash(request, "Result saved.")
    except ValueError as e:
        db.rollback()
        flash(request, str(e) if isinstance(e, ERRORS) else "Please enter numbers.", "error")
        return redirect(f"/beerpong/tournaments/{t.id}/matches/{tm.id}")
    return redirect(f"/beerpong/tournaments/{t.id}")


@router.post("/tournaments/{tid}/matches/{mid}/reset")
def bp_tmatch_reset(tid: int, mid: int, request: Request, db: Session = Depends(get_db),
                    user: models.User = Depends(require_user)):
    t = _tournament(db, tid)
    tm = _tmatch(t, mid)
    if not tour.can_organize(user, t):
        raise HTTPException(403)
    try:
        bp.reset_tournament_match(db, t, tm)
        flash(request, "Result reset.")
    except ERRORS as e:
        db.rollback()
        flash(request, str(e), "error")
    return redirect(f"/beerpong/tournaments/{t.id}/matches/{tm.id}")


@router.post("/tournaments/{tid}/delete")
def bp_tournament_delete(tid: int, request: Request, db: Session = Depends(get_db),
                         user: models.User = Depends(require_user)):
    t = _tournament(db, tid)
    if not tour.can_organize(user, t):
        raise HTTPException(403)
    name = t.name
    db.delete(t)
    db.commit()
    flash(request, f"Tournament “{name}” deleted. Its games stay in the history.")
    return redirect("/beerpong/tournaments")
