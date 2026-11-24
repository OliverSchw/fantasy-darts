"""Gemeinsame Turnier-Seiten für alle Sportarten (Liste, Baum/Gruppen, Match, Ergebnis, Reset, Löschen).

Jede Sportart beschreibt in einem `Sport`-Adapter nur, was bei ihr anders ist: wie ein Spiel zum Match
gestartet wird, wie ein Ergebnis von Hand gespeichert wird, und wie die Punkte heißen (Legs / Becher).
"""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from .. import tournaments as tour
from ..auth import require_user
from ..db import get_db
from .common import flash, redirect, render


@dataclass(frozen=True)
class Sport:
    key: str  # "darts" | "beerpong" - gleich Tournament.sport
    base: str  # URL-Präfix des Bereichs, z. B. "/darts"
    icon: str
    entries_label: str  # "players" | "teams"
    score_label: str  # "legs" | "cups"
    find_game: Callable  # (db, tm) -> Spiel oder None (neuestes nicht abgebrochenes)
    game_url: Callable  # (game) -> URL
    start_game: Callable  # (db, t, tm, user) -> Spiel; wirft ValueError mit Meldung
    record: Callable  # (db, t, tm, s1, s2, user) -> None; Ergebnis von Hand
    reset: Callable  # (db, t, tm) -> None
    live_match_ids: Callable  # (db, [match_id]) -> set der Match-IDs mit laufendem Spiel
    summary: Callable  # (t) -> kurze Beschreibung der Einstellungen
    max_score: Callable  # (t, tm) -> höchster sinnvoller Wert im Ergebnis-Formular
    manual_hint: str  # Erklärung im Formular "Ergebnis von Hand"


def add_tournament_routes(router: APIRouter, sp: Sport) -> None:
    """Hängt die Turnier-Routen unter <router-Präfix>/tournaments an."""

    def _tournament(db: Session, tid: int) -> models.Tournament:
        t = db.get(models.Tournament, tid)
        if t is None or t.sport != sp.key:
            raise HTTPException(404)
        return t

    def _tmatch(t: models.Tournament, mid: int) -> models.TournamentMatch:
        tm = next((m for m in t.matches if m.id == mid), None)
        if tm is None:
            raise HTTPException(404)
        return tm

    def _organizer_only(user, t):
        if not tour.can_organize(user, t):
            raise HTTPException(403, "Only the organizer of this tournament can do that.")

    @router.get("/tournaments", name=f"{sp.key}_tournaments")
    def tournaments_list(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_user)):
        ts = db.scalars(select(models.Tournament).where(models.Tournament.sport == sp.key)
                        .order_by(models.Tournament.created_at.desc(), models.Tournament.id.desc())).all()
        return render(request, "tournament/list.html", user=user, sp=sp, tournaments=ts, entry_by_id=tour.entry_by_id)

    @router.get("/tournaments/{tid:int}", name=f"{sp.key}_tournament")
    def tournament_page(tid: int, request: Request, db: Session = Depends(get_db),
                        user: models.User = Depends(require_user)):
        t = _tournament(db, tid)
        return render(request, "tournament/page.html", user=user, sp=sp, t=t, cols=tour.columns(t),
                      groups=tour.group_view(t) if t.has_groups else [],
                      live=sp.live_match_ids(db, [m.id for m in t.matches]),
                      winner=tour.entry_by_id(t, t.winner_entry_id), organizer=tour.can_organize(user, t),
                      ko_started=tour.knockout_started(t), match_title=tour.match_title)

    @router.get("/tournaments/{tid:int}/matches/{mid:int}", name=f"{sp.key}_tournament_match")
    def match_page(tid: int, mid: int, request: Request, db: Session = Depends(get_db),
                   user: models.User = Depends(require_user)):
        t = _tournament(db, tid)
        tm = _tmatch(t, mid)
        game = sp.find_game(db, tm)
        return render(request, "tournament/match.html", user=user, sp=sp, t=t, tm=tm, title=tour.match_title(t, tm),
                      game=game, game_url=sp.game_url(game) if game else None,
                      organizer=tour.can_organize(user, t), changeable=tour.can_change(t, tm),
                      max_score=sp.max_score(t, tm), locked_reason=tour._locked_reason(t, tm))

    @router.post("/tournaments/{tid:int}/matches/{mid:int}/play")
    def match_play(tid: int, mid: int, request: Request, db: Session = Depends(get_db),
                   user: models.User = Depends(require_user)):
        t = _tournament(db, tid)
        tm = _tmatch(t, mid)
        players = {c.user_id for e in (tm.entry1, tm.entry2) if e for c in e.competitors}
        if not (tour.can_organize(user, t) or user.id in players):
            raise HTTPException(403, "Only the organizer and the players of this match can start it.")
        try:
            game = sp.start_game(db, t, tm, user)
        except ValueError as e:
            db.rollback()
            flash(request, str(e), "error")
            return redirect(f"{sp.base}/tournaments/{t.id}/matches/{tm.id}")
        return redirect(sp.game_url(game))

    @router.post("/tournaments/{tid:int}/matches/{mid:int}/result")
    async def match_result(tid: int, mid: int, request: Request, db: Session = Depends(get_db),
                           user: models.User = Depends(require_user)):
        t = _tournament(db, tid)
        tm = _tmatch(t, mid)
        _organizer_only(user, t)
        form = await request.form()
        try:
            s1, s2 = int(form.get("score1", "")), int(form.get("score2", ""))
        except ValueError:
            flash(request, "Please enter numbers.", "error")
            return redirect(f"{sp.base}/tournaments/{t.id}/matches/{tm.id}")
        try:
            sp.record(db, t, tm, s1, s2, user)
        except ValueError as e:
            db.rollback()
            flash(request, str(e), "error")
            return redirect(f"{sp.base}/tournaments/{t.id}/matches/{tm.id}")
        flash(request, "Result saved." + (" 🏆 The knockout stage is drawn!" if tm.group_no is not None
                                          and tour.knockout_started(t) else ""))
        return redirect(f"{sp.base}/tournaments/{t.id}")

    @router.post("/tournaments/{tid:int}/matches/{mid:int}/reset")
    def match_reset(tid: int, mid: int, request: Request, db: Session = Depends(get_db),
                    user: models.User = Depends(require_user)):
        t = _tournament(db, tid)
        tm = _tmatch(t, mid)
        _organizer_only(user, t)
        try:
            sp.reset(db, t, tm)
            flash(request, "Result reset.")
        except ValueError as e:
            db.rollback()
            flash(request, str(e), "error")
        return redirect(f"{sp.base}/tournaments/{t.id}/matches/{tm.id}")

    @router.post("/tournaments/{tid:int}/knockout/reset")
    def knockout_reset(tid: int, request: Request, db: Session = Depends(get_db),
                       user: models.User = Depends(require_user)):
        t = _tournament(db, tid)
        _organizer_only(user, t)
        try:
            tour.reset_knockout(db, t)
            flash(request, "Knockout stage removed – group results can be changed again.")
        except ValueError as e:
            db.rollback()
            flash(request, str(e), "error")
        return redirect(f"{sp.base}/tournaments/{t.id}")

    @router.post("/tournaments/{tid:int}/delete")
    def tournament_delete(tid: int, request: Request, db: Session = Depends(get_db),
                          user: models.User = Depends(require_user)):
        t = _tournament(db, tid)
        _organizer_only(user, t)
        name = t.name
        db.delete(t)
        db.commit()
        flash(request, f"Tournament “{name}” deleted. Its games stay in the history.")
        return redirect(f"{sp.base}/tournaments")


def read_format(form) -> tuple[int | None, int]:
    """Turnierformat aus dem Formular: (Anzahl Gruppen oder None für reines K.-o., Qualifikanten pro Gruppe)."""
    if form.get("format") != "groups":
        return None, 2
    try:
        return int(form.get("groups", 2)), int(form.get("advance", 2))
    except ValueError:
        raise tour.TournamentError("Choose the number of groups and how many go through.") from None
