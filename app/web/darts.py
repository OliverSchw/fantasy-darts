"""Darts-Bereich: Spiele anlegen, live zählen, Verlauf und Stats. Nur für eingeloggte Mitglieder."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from .. import tournaments as tour
from ..auth import require_admin, require_user
from .. import competitors
from ..competitors import CompetitorError
from ..darts import service
from ..darts.checkouts import checkout_route, is_finishable, min_darts
from ..darts.engine import START_SCORES, DartsError
from ..darts.modes import MODES, dart_label, new_mode_state
from ..darts.stats import compare_rows, compute_stats, head_to_head, mode_records
from ..db import get_db
from .common import flash, redirect, render
from .tournament_pages import Sport, add_tournament_routes, read_boards, read_format

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
    """Für Listen: pro Seite (Spieler bzw. Team) Name, Bilder, gewonnene Legs und ob gewonnen."""
    out = []
    for g in games:
        legs = [0] * g.n_sides
        for v in g.visits:
            if v.checkout:
                legs[g.side_of(v.position)] += 1
        sides = [{"name": g.side_name(s), "comps": [p.competitor for p in g.side_players(s)], "legs": legs[s],
                  "win": g.status == "finished" and g.winning_side == s} for s in range(g.n_sides)]
        out.append({"game": g, "sides": sides})
    return out


# ---------------------------------------------------------------- Übersicht


@router.get("")
def darts_home(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    me = competitors.competitor_for_user(db, user)
    stats = compute_stats(db, [me.id])
    return render(request, "darts/home.html", user=user, me=me, my_stats=stats.get(me.id),
                  live=_game_summaries(_recent_games(db, 20, "live")), running=tour.running(db, "darts"),
                  recent=_game_summaries(_recent_games(db, 8, "finished")))


@router.get("/games")
def darts_games(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    return render(request, "darts/games.html", user=user, games=_game_summaries(_recent_games(db, 100)))


# ---------------------------------------------------------------- Neues Spiel


@router.get("/new")
def new_game_form(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    me = competitors.competitor_for_user(db, user)
    return render(request, "darts/new.html", user=user, competitors=competitors.all_competitors(db),
                  starts=START_SCORES, modes=MODES,
                  form={"start": 501, "legs": 3, "players": [me.id], "team_size": 1, "mode": "x01", "lives": 3, "rounds": 7})


@router.post("/new")
async def new_game(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    form = await request.form()
    try:
        start = int(form.get("start", 501))
        legs = int(form.get("legs", 1))
        team_size = 2 if str(form.get("team_size", "1")) == "2" else 1
        lives, rounds = int(form.get("lives", 3) or 3), int(form.get("rounds", 7) or 7)
    except ValueError:
        start, legs, team_size, lives, rounds = 0, 0, 1, 3, 7
    mode = str(form.get("mode", "x01"))
    mode = mode if mode in MODES else "x01"
    ids, errors = [], []
    for i in range(4):
        raw = str(form.get(f"p{i}", "")).strip()
        guest = str(form.get(f"g{i}", "")).strip()
        try:
            if raw == "guest" and guest:
                ids.append(competitors.create_guest(db, guest).id)
            elif raw.isdigit():
                ids.append(int(raw))
        except (DartsError, CompetitorError) as e:
            errors.append(str(e))
    try:
        if errors:
            raise DartsError(errors[0])
        if mode == "x01":
            game = service.create_game(db, start, legs, ids, user, team_size=team_size)
        else:
            opts = {"lives": lives} if mode == "killer" else ({"rounds": rounds} if mode == "shanghai" else {})
            game = service.create_mode_game(db, mode, ids, user, opts)
    except DartsError as e:
        db.rollback()
        return render(request, "darts/new.html", status_code=400, user=user, error=str(e),
                      competitors=competitors.all_competitors(db), starts=START_SCORES, modes=MODES,
                      form={"start": start or 501, "legs": legs or 1, "players": ids, "team_size": team_size,
                            "mode": mode, "lives": lives, "rounds": rounds})
    return redirect(f"/darts/games/{game.id}")


# ---------------------------------------------------------------- Spiel


@router.get("/games/{game_id}")
def game_page(game_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    game = _game(db, game_id)
    if game.mode != "x01":
        return _mode_page(request, db, user, game)
    state = service.game_state(game)
    # Eine Karte pro Seite (Einzel: pro Spieler, Doppel: pro Team)
    cards = []
    for side in range(state.n_sides):
        members = game.side_players(side)
        positions = {p.position for p in members}
        leg = [v for v in game.visits if v.position in positions and v.leg_no == state.leg_no]
        all_ = [v for v in game.visits if v.position in positions]
        avg = lambda vs: 3 * sum(v.score for v in vs) / sum(v.darts for v in vs) if vs else None  # noqa: E731
        cards.append({
            "side": side, "c": members[0].competitor, "comps": [p.competitor for p in members],
            "name": game.side_name(side), "remaining": state.remaining[side], "legs": state.legs_won[side],
            "turn": not state.finished and state.side(state.turn) == side,
            "thrower": game.players[state.turn].competitor.display_name
                       if state.team_size > 1 and not state.finished and state.side(state.turn) == side else None,
            "leg_avg": avg(leg), "game_avg": avg(all_), "last": leg[-1] if leg else None,
            "darts": sum(v.darts for v in leg),
        })
    rest = state.remaining[state.side(state.turn)] if not state.finished else None
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
        request, "darts/game.html", user=user, game=game, gs=state, cards=cards, throwers=game.players,
        can_score=service.can_score(user, game), can_manage=service.can_manage(user, game),
        rest=rest, route=checkout_route(rest) if rest else None,
        finishable=bool(rest and is_finishable(rest)), min_darts=min_darts(rest) if rest else None,
        rounds=rounds, shown_leg=shown_leg, n_visits=len(game.visits), tinfo=_tournament_info(db, game),
    )


def _mode_page(request: Request, db: Session, user: models.User, game: models.DartsGame):
    s = service.mode_state(game)
    rows = []
    for p in game.players:
        i = p.position
        rows.append({
            "p": p, "c": p.competitor, "turn": not s.finished and s.turn == i, "won": s.winner == i,
            "points": s.points[i] if s.points else 0,
            "marks": s.marks[i] if s.marks else None,
            "target": s.target[i] if s.target else None,
            "lives": s.lives[i] if s.lives else None, "killer": s.killer[i] if s.killer else None,
            "number": s.numbers[i] if s.numbers else None, "alive": s.alive(i),
            "last": next((v for v in reversed(game.visits) if v.position == i), None),
        })
    return render(request, "darts/game_mode.html", user=user, game=game, s=s, rows=rows, info=MODES[game.mode],
                  can_score=service.can_score(user, game), can_manage=service.can_manage(user, game),
                  n_visits=len(game.visits), dart_label=dart_label,
                  history=list(reversed(game.visits[-12:])))


@router.post("/games/{game_id}/throws")
async def post_throws(game_id: int, request: Request, db: Session = Depends(get_db),
                      user: models.User = Depends(require_user)):
    game = _game(db, game_id)
    if game.mode == "x01":
        raise HTTPException(400, "X01 games are scored per visit.")
    if not service.can_score(user, game):
        raise HTTPException(403, "Only the players and whoever started the game can score.")
    form = await request.form()
    throws = [t for t in str(form.get("throws", "")).split(",") if t.strip()]
    try:
        seq = int(str(form.get("seq", "-1")))
        result = service.add_mode_visit(db, game, throws, seq)
        for msg in result["log"]:
            if msg in ("Shanghai!", "Killer!"):
                flash(request, f"🎯 {msg}")
        if game.status == "finished":
            flash(request, f"🏆 {game.side_name(game.winning_side)} wins {MODES[game.mode]['name']}!")
    except (DartsError, ValueError) as e:
        db.rollback()
        flash(request, str(e) if isinstance(e, DartsError) else "Invalid input.", "error")
    return redirect(f"/darts/games/{game.id}")


@router.get("/games/{game_id}/version")
def game_version(game_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    """Für die Live-Ansicht: ändert sich, sobald jemand eine Aufnahme einträgt."""
    game = _game(db, game_id)
    return JSONResponse({"v": len(game.visits), "status": game.status}, headers={"Cache-Control": "no-store"})


@router.post("/games/{game_id}/visit")
async def post_visit(game_id: int, request: Request, db: Session = Depends(get_db),
                     user: models.User = Depends(require_user)):
    game = _game(db, game_id)
    if game.mode != "x01":
        raise HTTPException(400, "This game is scored dart by dart.")
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
            team = game.side_name(game.winning_side)
            flash(request, f"🎯 Game shot! {team} {'win' if (game.team_size or 1) > 1 else 'wins'}.")
    except DartsError as e:
        db.rollback()
        flash(request, str(e), "error")
    return redirect(f"/darts/games/{game.id}")


@router.post("/games/{game_id}/undo")
def post_undo(game_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    game = _game(db, game_id)
    if not service.can_manage(user, game):
        raise HTTPException(403)
    try:
        if service.undo_last(db, game):
            flash(request, "Last visit undone.")
    except DartsError as e:
        db.rollback()
        flash(request, str(e), "error")
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
    people = competitors.all_competitors(db)
    stats = compute_stats(db)
    rows = [(c, stats[c.id]) for c in people if c.id in stats]  # nur wer schon geworfen hat
    rows.sort(key=lambda r: (r[1].average is None, -(r[1].average or 0)))
    return render(request, "darts/players.html", user=user, rows=rows)


def _pick(db: Session, raw: str | None) -> models.Competitor | None:
    return db.get(models.Competitor, int(raw)) if raw and raw.isdigit() else None


@router.get("/compare")
def compare_page(request: Request, a: str | None = None, b: str | None = None, db: Session = Depends(get_db),
                 user: models.User = Depends(require_user)):
    ca = _pick(db, a) or competitors.competitor_for_user(db, user)
    cb = _pick(db, b)
    ctx = {"people": competitors.all_competitors(db), "a": ca, "b": cb}
    if ca and cb and ca.id != cb.id:
        stats = compute_stats(db, [ca.id, cb.id])
        h2h = head_to_head(db, ca.id, cb.id)
        games = db.scalars(select(models.DartsGame).where(models.DartsGame.id.in_(h2h.game_ids[:5]))
                           .order_by(models.DartsGame.created_at.desc())).all() if h2h.game_ids else []
        rows, h2h_rows = compare_rows(stats.get(ca.id), stats.get(cb.id)), compare_rows(h2h.stats_a, h2h.stats_b)
        ctx.update(rows=rows, h2h=h2h, h2h_rows=None if h2h_rows == rows else h2h_rows,
                   h2h_games=_game_summaries(games))
    return render(request, "darts/compare.html", user=user, **ctx)


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
                  records=mode_records(db, [c.id]).get(c.id, {}),
                  games=_game_summaries(_recent_games(db, 15, competitor_id=c.id)))


@router.post("/players/{competitor_id}/link")
async def link_guest(competitor_id: int, request: Request, db: Session = Depends(get_db),
                     admin: models.User = Depends(require_admin)):
    """Admin: Gast einem Konto zuordnen (z. B. nachdem sich jemand registriert hat). Stats wandern mit."""
    c = db.get(models.Competitor, competitor_id)
    form = await request.form()
    raw = str(form.get("user_id", ""))
    target = db.get(models.User, int(raw)) if raw.isdigit() else None
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


# ---------------------------------------------------------------- Turniere


def _tournament_info(db: Session, game: models.DartsGame) -> dict | None:
    if not game.tournament_match_id:
        return None
    tm = db.get(models.TournamentMatch, game.tournament_match_id)
    if tm is None:
        return None
    t = db.get(models.Tournament, tm.tournament_id)
    return {"t": t, "tm": tm, "title": tour.match_title(t, tm)}


@router.get("/tournaments/new")
def new_tournament_form(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    return render(request, "darts/tournament_new.html", user=user, competitors=competitors.all_competitors(db),
                  starts=START_SCORES, modes=MODES,
                  form={"start": 501, "legs": 2, "final_legs": 3, "players": [], "shuffle": True,
                        "name": "", "guests": "", "format": "knockout", "groups": "", "advance": "2",
                        "boards": 0, "mode": "x01", "teams": "singles", "team_text": "", "lives": 3, "rounds": 7})


@router.post("/tournaments/new")
async def new_tournament(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
    form = await request.form()
    try:
        start, legs, final_legs = int(form.get("start", 501)), int(form.get("legs", 2)), int(form.get("final_legs", 3))
    except ValueError:
        start, legs, final_legs = 0, 0, 0
    players = [int(x) for x in form.getlist("players") if str(x).isdigit()]
    guests_raw = str(form.get("guests", ""))
    keep = {"start": start or 501, "legs": legs or 2, "final_legs": final_legs or 3, "players": players,
            "shuffle": bool(form.get("shuffle")), "name": str(form.get("name", "")), "guests": guests_raw,
            "format": form.get("format") or "knockout", "groups": str(form.get("groups", "")), "advance": str(form.get("advance", "2")),
            "boards": str(form.get("boards", "0")),
            "mode": form.get("mode") if form.get("mode") in MODES else "x01",
            "teams": form.get("teams") if form.get("teams") in ("random", "fixed") else "singles",
            "team_text": str(form.get("team_text", "")),
            "lives": int(form.get("lives") or 3) if str(form.get("lives", "3")).isdigit() else 3,
            "rounds": int(form.get("rounds") or 7) if str(form.get("rounds", "7")).isdigit() else 7}
    try:
        mode, teams = keep["mode"], keep["teams"]
        if mode == "x01" and (start not in START_SCORES or not 1 <= legs <= 11 or not 1 <= final_legs <= 11):
            raise DartsError("Pick a start score and 1-11 legs.")
        if mode != "x01" and teams != "singles":
            raise DartsError("Doubles tournaments are played in X01.")
        groups, advance = read_format(form)
        names = None
        if teams == "fixed":
            entries, names = competitors.parse_teams(db, keep["team_text"])
            if any(len(e) != 2 for e in entries):
                raise DartsError("Doubles teams need exactly 2 players each.")
        else:
            ids = list(players)
            for name in [g.strip() for g in guests_raw.replace(",", "\n").splitlines() if g.strip()]:
                ids.append(competitors.create_guest(db, name).id)
            entries = competitors.random_pairs(ids) if teams == "random" else [[i] for i in ids]
        settings = {"start": start, "legs": legs, "final_legs": final_legs, "boards": read_boards(form),
                    "mode": mode, "team_size": 1 if teams == "singles" else 2}
        if mode == "killer":
            settings["lives"] = keep["lives"]
        if mode == "shanghai":
            settings["rounds"] = keep["rounds"]
        if mode != "x01":  # Partyspiele: ein Spiel pro Match
            settings.update(legs=1, final_legs=1)
            new_mode_state(  # Optionen gleich prüfen (Leben, Runden)
                mode, 2, {"lives": keep["lives"], "rounds": keep["rounds"], "numbers": [1, 2]})
        t = tour.create_tournament(db, "darts", keep["name"], entries, settings, user,
                                   shuffle=keep["shuffle"], groups=groups, advance=advance, entry_names=names)
    except (DartsError, CompetitorError, tour.TournamentError) as e:
        db.rollback()
        return render(request, "darts/tournament_new.html", status_code=400, user=user, error=str(e),
                      competitors=competitors.all_competitors(db), starts=START_SCORES, modes=MODES, form=keep)
    flash(request, f"Tournament “{t.name}” is on – {len(t.entries)} {'teams' if keep['teams'] != 'singles' else 'players'}.")
    return redirect(f"/darts/tournaments/{t.id}")


def _darts_live_ids(db: Session, match_ids: list[int]) -> set[int]:
    return set(db.scalars(select(models.DartsGame.tournament_match_id).where(
        models.DartsGame.tournament_match_id.in_(match_ids), models.DartsGame.status == "live")))


def _darts_tournament_stats(db: Session, t: models.Tournament) -> dict[int, dict]:
    """Average, 180er ... jedes Spielers, nur aus den Darts-Spielen dieses Turniers (nicht abgebrochen)."""
    game_ids = list(db.scalars(select(models.DartsGame.id).where(
        models.DartsGame.tournament_match_id.in_([m.id for m in t.matches]), models.DartsGame.status != "abandoned")))
    if not game_ids:
        return {}
    stats = compute_stats(db, [c.id for e in t.entries for c in e.competitors], game_ids=game_ids)
    out = {}
    for e in t.entries:
        s = stats.get(e.competitors[0].id) if e.competitors else None
        if s:
            out[e.id] = {"average": s.average, "max180": s.max180, "high_finish": s.high_finish or None,
                         "checkout_pct": s.checkout_pct}
    return out


def _darts_settings(t: models.Tournament) -> str:
    s = service.tournament_settings(t)
    if s["mode"] != "x01":
        return MODES[s["mode"]]["name"]
    doubles = " · doubles" if s.get("team_size") == 2 else ""
    return f"{s['start']}{doubles} · first to {s['legs']}, final first to {s['final_legs']}"


def _darts_live_status(db: Session, tm: models.TournamentMatch) -> dict | None:
    """Kurzer Live-Stand eines Turnier-Matches für die TV-Ansicht."""
    g = service.tournament_game(db, tm)
    if g is None or g.status != "live":
        return None
    if g.mode == "x01":
        st = service.game_state(g)
        return {"score": " : ".join(str(r) for r in st.remaining),
                "detail": f"Leg {st.leg_no} · legs {' : '.join(str(x) for x in st.legs_won)}"
                          + (f" · {g.players[st.turn].competitor.display_name} to throw" if not st.finished else "")}
    s = service.mode_state(g)
    if g.mode == "cricket":
        closed = [sum(1 for v in m.values() if v >= 3) for m in s.marks]
        return {"score": " : ".join(str(p) for p in s.points), "detail": f"closed {' : '.join(map(str, closed))} of 7"}
    if g.mode == "atc":
        return {"score": " : ".join("Bull" if x == 25 else str(x) for x in s.target), "detail": "targets"}
    if g.mode == "shanghai":
        return {"score": " : ".join(str(p) for p in s.points), "detail": f"round {s.shanghai_round} – target {s.shanghai_number()}"}
    return {"score": " : ".join(str(x) for x in s.lives), "detail": "lives"}


add_tournament_routes(router, Sport(
    key="darts", base="/darts", icon="🎯", entries_label="players", score_label="legs",
    find_game=service.tournament_game, game_url=lambda g: f"/darts/games/{g.id}",
    start_game=service.start_tournament_game,
    record=lambda db, t, tm, s1, s2, user: service.record_tournament_result(db, t, tm, s1, s2),
    reset=lambda db, t, tm: tour.clear_result(db, t, tm),
    live_match_ids=_darts_live_ids, summary=_darts_settings,
    max_score=lambda t, tm: service.legs_for(t, tm),
    manual_hint="For a match played without the app: legs won by each player.",
    extra_columns=(("average", "Avg", "avg"), ("max180", "180s", "int"), ("high_finish", "HF", "int"),
                   ("checkout_pct", "CO%", "pct")),
    extra_stats=_darts_tournament_stats, live_status=_darts_live_status,
))
