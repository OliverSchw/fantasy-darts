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
from .tournament_pages import Sport, add_tournament_routes, read_boards, read_format, read_league

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
                  live=_games(db, 20, "live"), recent=_games(db, 8, "finished"), running=tour.running(db, "beerpong"))


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
                  tinfo={"t": t, "tm": tm, "title": tour.match_title(t, tm)} if t else None)


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


@router.get("/compare")
def bp_compare(request: Request, a: str | None = None, b: str | None = None, db: Session = Depends(get_db),
               user: models.User = Depends(require_user)):
    pick = lambda raw: db.get(models.Competitor, int(raw)) if raw and raw.isdigit() else None  # noqa: E731
    ca = pick(a) or competitors.competitor_for_user(db, user)
    cb = pick(b)
    ctx = {"people": competitors.all_competitors(db), "a": ca, "b": cb}
    if ca and cb and ca.id != cb.id:
        stats = bp.compute_stats(db, [ca.id, cb.id])
        ctx.update(rows=bp.compare_rows(stats.get(ca.id), stats.get(cb.id)), riv=bp.rivalry(db, ca.id, cb.id))
    return render(request, "beerpong/compare.html", user=user, **ctx)


# ---------------------------------------------------------------- Turniere


def _bp_form(request: Request, db: Session, user: models.User, league: bool):
    return render(request, "beerpong/tournament_new.html", user=user, competitors=competitors.all_competitors(db),
                  cup_options=bp.CUP_OPTIONS, active_tab="/beerpong/leagues" if league else "/beerpong/tournaments",
                  form={"name": "", "cups": 10, "mode": "random", "players": [], "guests": "", "teams": "", "shuffle": True,
                        "format": "league" if league else "knockout", "groups": "", "advance": "2",
                        "league_rounds": "1", "boards": 0})


@router.get("/tournaments/new")
def bp_tournament_form(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    return _bp_form(request, db, user, league=False)


@router.get("/leagues/new")
def bp_league_form(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    return _bp_form(request, db, user, league=True)


@router.post("/tournaments/new")
async def bp_tournament_new(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    form = await request.form()
    keep = {"name": str(form.get("name", "")), "cups": int(form.get("cups") or 10) if str(form.get("cups", "")).isdigit() else 10,
            "mode": "fixed" if form.get("mode") == "fixed" else "random",
            "players": [int(x) for x in form.getlist("players") if str(x).isdigit()],
            "guests": str(form.get("guests", "")), "teams": str(form.get("teams", "")), "shuffle": bool(form.get("shuffle")),
            "format": form.get("format") or "knockout", "groups": str(form.get("groups", "")), "advance": str(form.get("advance", "2")),
            "league_rounds": str(form.get("league_rounds", "1")),
            "boards": str(form.get("boards", "0"))}
    try:
        if keep["cups"] not in bp.CUP_OPTIONS:
            raise bp.BeerpongError("Play with 6 or 10 cups.")
        groups, advance = read_format(form)
        if keep["mode"] == "fixed":
            teams, names = competitors.parse_teams(db, keep["teams"])
        else:
            ids = list(keep["players"])
            for name in [g.strip() for g in keep["guests"].replace(",", "\n").splitlines() if g.strip()]:
                ids.append(competitors.create_guest(db, name).id)
            teams, names = competitors.random_pairs(ids), None
        t = tour.create_tournament(db, "beerpong", keep["name"], teams, {"cups": keep["cups"], "boards": read_boards(form)}, user,
                                   shuffle=keep["shuffle"], entry_names=names, groups=groups, advance=advance, league_rounds=read_league(form))
    except ERRORS as e:
        db.rollback()
        return render(request, "beerpong/tournament_new.html", status_code=400, user=user, error=str(e),
                      competitors=competitors.all_competitors(db), cup_options=bp.CUP_OPTIONS, form=keep)
    flash(request, f"{'League' if t.is_league else 'Tournament'} “{t.name}” is on – {len(t.entries)} teams.")
    return redirect(f"/beerpong/tournaments/{t.id}")


def _bp_live_ids(db: Session, match_ids: list[int]) -> set[int]:
    return set(db.scalars(select(models.BeerpongGame.tournament_match_id).where(
        models.BeerpongGame.tournament_match_id.in_(match_ids), models.BeerpongGame.status == "live")))


def _bp_live_status(db: Session, tm: models.TournamentMatch) -> dict | None:
    g = bp.tournament_game(db, tm)
    if g is None or g.status != "live":
        return None
    return {"score": f"{g.hits1} : {g.hits2}", "detail": f"cups hit (of {g.cups})"}


add_tournament_routes(router, Sport(
    key="beerpong", base="/beerpong", icon="🍺", entries_label="teams", score_label="cups",
    find_game=bp.tournament_game, game_url=lambda g: f"/beerpong/games/{g.id}",
    start_game=bp.start_tournament_game, record=bp.record_tournament_result, reset=bp.reset_tournament_match,
    live_match_ids=_bp_live_ids, summary=lambda t: f"{t.settings.get('cups', 10)} cups",
    max_score=lambda t, tm: int(t.settings.get("cups", 10)),
    manual_hint="Cups hit by each team – the winner hits all of them.", board_label="Table",
    live_status=_bp_live_status,
    extra_columns=(("cups_per_game", "Cups/game", "dec"),),
    extra_stats=lambda db, t: {r.entry.id: {"cups_per_game": r.score_for / r.played if r.played else None}
                               for r in tour.entry_results(t)},
))
