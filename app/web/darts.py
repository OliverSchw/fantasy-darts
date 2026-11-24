"""Darts-Bereich: Spiele anlegen, live zählen, Verlauf und Stats. Nur für eingeloggte Mitglieder."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..auth import require_admin, require_user
from ..darts import service
from ..darts.checkouts import checkout_route, is_finishable, min_darts
from ..darts.engine import START_SCORES, DartsError
from ..darts.stats import compute_stats, leg_average
from ..db import get_db
from .common import flash, redirect, render

router = APIRouter(prefix="/darts")


def _game(db: Session, game_id: int) -> models.DartsGame:
    game = db.get(models.DartsGame, game_id)
    if game is None:
        raise HTTPException(404)
    return game


def _recent_games(db: Session, limit: int, status: str | None = None, competitor_id: int | None = None):
    q = select(models.DartsGame).where(models.DartsGame.status != "abandoned")
    if status:
        q = q.where(models.DartsGame.status == status)
    if competitor_id is not None:
        q = q.where(models.DartsGame.id.in_(
            select(models.DartsGamePlayer.game_id).where(models.DartsGamePlayer.competitor_id == competitor_id)))
    return db.scalars(q.order_by(models.DartsGame.created_at.desc(), models.DartsGame.id.desc()).limit(limit)).all()


def _game_summaries(games: list[models.DartsGame]) -> list[dict]:
    """Für Listen: Legs je Spieler aus den Aufnahmen."""
    out = []
    for g in games:
        legs = {p.position: 0 for p in g.players}
        for v in g.visits:
            if v.checkout:
                legs[v.position] += 1
        out.append({"game": g, "legs": legs})
    return out


# ---------------------------------------------------------------- Übersicht


@router.get("")
def darts_home(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    me = service.competitor_for_user(db, user)
    stats = compute_stats(db, [me.id])
    return render(request, "darts/home.html", user=user, me=me, my_stats=stats.get(me.id),
                  live=_game_summaries(_recent_games(db, 20, "live")),
                  recent=_game_summaries(_recent_games(db, 8, "finished")))


@router.get("/games")
def darts_games(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    return render(request, "darts/games.html", user=user, games=_game_summaries(_recent_games(db, 100)))


# ---------------------------------------------------------------- Neues Spiel


@router.get("/new")
def new_game_form(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    me = service.competitor_for_user(db, user)
    return render(request, "darts/new.html", user=user, competitors=service.all_competitors(db),
                  starts=START_SCORES, form={"start": 501, "legs": 3, "players": [me.id]})


@router.post("/new")
async def new_game(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    form = await request.form()
    try:
        start = int(form.get("start", 501))
        legs = int(form.get("legs", 1))
    except ValueError:
        start, legs = 0, 0
    ids, errors = [], []
    for i in range(4):
        raw = str(form.get(f"p{i}", "")).strip()
        guest = str(form.get(f"g{i}", "")).strip()
        try:
            if raw == "guest" and guest:
                ids.append(service.create_guest(db, guest).id)
            elif raw.isdigit():
                ids.append(int(raw))
        except DartsError as e:
            errors.append(str(e))
    try:
        if errors:
            raise DartsError(errors[0])
        game = service.create_game(db, start, legs, ids, user)
    except DartsError as e:
        db.rollback()
        return render(request, "darts/new.html", status_code=400, user=user, error=str(e),
                      competitors=service.all_competitors(db), starts=START_SCORES,
                      form={"start": start or 501, "legs": legs or 1, "players": ids})
    return redirect(f"/darts/games/{game.id}")


# ---------------------------------------------------------------- Spiel


@router.get("/games/{game_id}")
def game_page(game_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    game = _game(db, game_id)
    state = service.game_state(game)
    players = []
    for p in game.players:
        last = next((v for v in reversed(game.visits) if v.position == p.position and v.leg_no == state.leg_no), None)
        players.append({
            "p": p, "c": p.competitor, "remaining": state.remaining[p.position], "legs": state.legs_won[p.position],
            "turn": not state.finished and state.turn == p.position,
            "leg_avg": leg_average(game.visits, p.competitor_id, state.leg_no),
            "game_avg": leg_average(game.visits, p.competitor_id),
            "last": last, "darts": sum(v.darts for v in game.visits if v.position == p.position and v.leg_no == state.leg_no),
        })
    rest = state.remaining[state.turn] if not state.finished else None
    # Verlauf des laufenden (bzw. letzten) Legs als Runden: [[visit spieler 0, visit spieler 1], ...]
    shown_leg = state.leg_no if not state.finished else (game.visits[-1].leg_no if game.visits else 1)
    leg_visits = [v for v in game.visits if v.leg_no == shown_leg]
    rounds: list[dict] = []
    per_player: dict[int, int] = {}
    for v in leg_visits:
        i = per_player.get(v.position, 0)
        per_player[v.position] = i + 1
        if i == len(rounds):
            rounds.append({})
        rounds[i][v.position] = {"v": v, "left": v.remaining_before - v.score}
    return render(
        request, "darts/game.html", user=user, game=game, gs=state, players=players,
        can_score=service.can_score(user, game), can_manage=service.can_manage(user, game),
        rest=rest, route=checkout_route(rest) if rest else None,
        finishable=bool(rest and is_finishable(rest)), min_darts=min_darts(rest) if rest else None,
        rounds=rounds, shown_leg=shown_leg, n_visits=len(game.visits),
    )


@router.get("/games/{game_id}/version")
def game_version(game_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    """Für die Live-Ansicht: ändert sich, sobald jemand eine Aufnahme einträgt."""
    game = _game(db, game_id)
    return JSONResponse({"v": len(game.visits), "status": game.status}, headers={"Cache-Control": "no-store"})


@router.post("/games/{game_id}/visit")
async def post_visit(game_id: int, request: Request, db: Session = Depends(get_db),
                     user: models.User = Depends(require_user)):
    game = _game(db, game_id)
    if not service.can_score(user, game):
        raise HTTPException(403, "Only the players and whoever started the game can score.")
    form = await request.form()
    try:
        score = int(str(form.get("score", "")).strip())
        seq = int(str(form.get("seq", "-1")))
        darts_raw = str(form.get("darts", "")).strip()
        darts = int(darts_raw) if darts_raw else None
    except ValueError:
        flash(request, "Please enter a number.", "error")
        return redirect(f"/darts/games/{game.id}")
    try:
        visit = service.add_visit(db, game, score, darts, seq)
        if visit.bust:
            flash(request, f"Bust! {score} was too much – no score.", "error")
        elif game.status == "finished":
            flash(request, f"🎯 Game shot! {game.winner.display_name} wins.")
    except DartsError as e:
        db.rollback()
        flash(request, str(e), "error")
    return redirect(f"/darts/games/{game.id}")


@router.post("/games/{game_id}/undo")
def post_undo(game_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    game = _game(db, game_id)
    if not service.can_manage(user, game):
        raise HTTPException(403)
    if service.undo_last(db, game):
        flash(request, "Last visit undone.")
    return redirect(f"/darts/games/{game.id}")


@router.post("/games/{game_id}/abandon")
def post_abandon(game_id: int, request: Request, db: Session = Depends(get_db),
                 user: models.User = Depends(require_user)):
    game = _game(db, game_id)
    if not service.can_manage(user, game):
        raise HTTPException(403)
    service.abandon(db, game)
    flash(request, "Game abandoned – it doesn't count for the stats.")
    return redirect("/darts")


# ---------------------------------------------------------------- Spieler & Stats


@router.get("/players")
def players_page(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    competitors = service.all_competitors(db)
    stats = compute_stats(db)
    rows = [(c, stats[c.id]) for c in competitors if c.id in stats]  # nur wer schon geworfen hat
    rows.sort(key=lambda r: (r[1].average is None, -(r[1].average or 0)))
    return render(request, "darts/players.html", user=user, rows=rows)


@router.get("/players/{competitor_id}")
def player_page(competitor_id: int, request: Request, db: Session = Depends(get_db),
                user: models.User = Depends(require_user)):
    c = db.get(models.Competitor, competitor_id)
    if c is None:
        raise HTTPException(404)
    stats = compute_stats(db, [c.id]).get(c.id)
    users = (db.scalars(select(models.User).order_by(func.lower(models.User.username))).all()
             if user.is_admin and c.is_guest else [])
    return render(request, "darts/player.html", user=user, c=c, stats=stats, link_users=users,
                  games=_game_summaries(_recent_games(db, 15, competitor_id=c.id)))


@router.post("/players/{competitor_id}/link")
async def link_guest(competitor_id: int, request: Request, db: Session = Depends(get_db),
                     admin: models.User = Depends(require_admin)):
    """Admin: Gast einem Konto zuordnen (z. B. nachdem sich jemand registriert hat). Stats wandern mit."""
    c = db.get(models.Competitor, competitor_id)
    form = await request.form()
    target = db.get(models.User, int(form.get("user_id") or 0))
    if c is None or target is None or not c.is_guest:
        raise HTTPException(404)
    existing = db.scalar(select(models.Competitor).where(models.Competitor.user_id == target.id))
    if existing is not None:
        games_of = lambda cid: set(db.scalars(select(models.DartsGamePlayer.game_id)  # noqa: E731
                                              .where(models.DartsGamePlayer.competitor_id == cid)))
        if games_of(existing.id) & games_of(c.id):
            flash(request, f"“{c.name}” and {target.username} played in the same game – can't merge them.", "error")
            return redirect(f"/darts/players/{c.id}")
        # Das Konto hat schon einen Teilnehmer: dessen (meist leere) Daten auf den Gast übertragen
        for table in (models.DartsGamePlayer, models.DartsVisit):
            db.execute(table.__table__.update().where(table.competitor_id == existing.id).values(competitor_id=c.id))
        db.execute(models.DartsGame.__table__.update().where(models.DartsGame.winner_id == existing.id)
                   .values(winner_id=c.id))
        db.delete(existing)
        db.flush()
    c.user_id = target.id
    db.commit()
    flash(request, f"“{c.name}” is now linked to the account {target.username}.")
    return redirect(f"/darts/players/{c.id}")
