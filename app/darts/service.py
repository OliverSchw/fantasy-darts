"""Darts: Datenbank-Operationen rund um Teilnehmer, Spiele und Aufnahmen."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from .. import models
from .. import tournaments as tour
from .engine import DartsError, GameState, Visit, advance, make_visit, new_state, replay


# ---------------------------------------------------------------- Spiele


def create_game(db: Session, start: int, legs_to_win: int, competitor_ids: list[int],
                created_by: models.User | None, team_size: int = 1) -> models.DartsGame:
    """competitor_ids in Wurfreihenfolge; Doppel (team_size 2): Team 1 = Positionen 0 und 2, Team 2 = 1 und 3."""
    if len(set(competitor_ids)) != len(competitor_ids):
        raise DartsError("Each player can only take part once.")
    new_state(start, legs_to_win, len(competitor_ids), team_size)  # prüft Start, Legs, Spielerzahl, Teams
    found = {c.id for c in db.scalars(select(models.Competitor).where(models.Competitor.id.in_(competitor_ids)))}
    if found != set(competitor_ids):
        raise DartsError("Unknown player.")
    game = models.DartsGame(start_score=start, legs_to_win=legs_to_win, team_size=team_size,
                            created_by_id=created_by.id if created_by else None)
    game.players = [models.DartsGamePlayer(position=i, competitor_id=cid) for i, cid in enumerate(competitor_ids)]
    db.add(game)
    db.commit()
    return game


def _engine_visits(game: models.DartsGame) -> list[Visit]:
    return [Visit(player=v.position, score=v.score, darts=v.darts, bust=v.bust, checkout=v.checkout)
            for v in game.visits]


def game_state(game: models.DartsGame) -> GameState:
    return replay(game.start_score, game.legs_to_win, len(game.players), _engine_visits(game), game.team_size or 1)


def can_manage(user: models.User | None, game: models.DartsGame) -> bool:
    """Zählen, rückgängig, abbrechen: wer das Spiel angelegt hat, Mitspieler mit Konto, Admins und bei
    Turnierspielen der Organisator des Turniers. Alle anderen schauen nur zu."""
    if user is None or game.status == "abandoned":
        return False
    return (user.is_admin or game.created_by_id == user.id
            or any(p.competitor.user_id == user.id for p in game.players)
            or tour.organizes_match(object_session(game), game.tournament_match_id, user))


def can_score(user: models.User | None, game: models.DartsGame) -> bool:
    return game.status == "live" and can_manage(user, game)


class StaleGame(DartsError):
    """Jemand anderes hat in der Zwischenzeit gezählt (oder doppelt abgeschickt)."""


def add_visit(db: Session, game: models.DartsGame, score: int, darts: int | None, seq: int) -> Visit:
    """Speichert die nächste Aufnahme. seq = Anzahl Aufnahmen, die die Seite kannte (gegen Doppel-Tipps)."""
    if game.status != "live":
        raise DartsError("This game is not running any more.")
    if seq != len(game.visits):
        raise StaleGame("The game was updated in the meantime – here is the latest score.")
    state = game_state(game)
    visit = make_visit(state, score, darts)
    db.add(models.DartsVisit(
        game_id=game.id, seq=seq, leg_no=state.leg_no, position=visit.player,
        competitor_id=game.players[visit.player].competitor_id, score=visit.score, darts=visit.darts,
        bust=visit.bust, checkout=visit.checkout, remaining_before=state.remaining[state.side(visit.player)],
    ))
    advance(state, visit)  # Stand fortschreiben, um das Spielende zu erkennen
    if state.finished:
        game.status = "finished"
        game.winner_side = state.winner
        game.winner_id = game.side_players(state.winner)[0].competitor_id
        game.finished_at = datetime.now(timezone.utc)
        _report_to_tournament(db, game, state)
    try:
        db.commit()
    except IntegrityError:  # gleichzeitig dieselbe Aufnahme von zwei Handys
        db.rollback()
        raise StaleGame("The game was updated in the meantime – here is the latest score.") from None
    db.refresh(game)
    return visit


def undo_last(db: Session, game: models.DartsGame) -> bool:
    """Letzte Aufnahme löschen. Ein beendetes Spiel läuft danach wieder."""
    if game.status == "abandoned" or not game.visits:
        return False
    if game.status == "finished" and game.tournament_match_id:
        tm = db.get(models.TournamentMatch, game.tournament_match_id)
        t = db.get(models.Tournament, tm.tournament_id)
        try:
            tour.clear_result(db, t, tm, commit=False)
        except tour.TournamentError as e:
            raise DartsError(str(e)) from None
    db.delete(game.visits[-1])
    game.status, game.winner_id, game.winner_side, game.finished_at = "live", None, None, None
    db.commit()
    db.refresh(game)
    return True


def abandon(db: Session, game: models.DartsGame) -> None:
    game.status = "abandoned"
    db.commit()


# ---------------------------------------------------------------- Turniere


TOURNAMENT_DEFAULTS = {"start": 501, "legs": 2, "final_legs": 3}


def legs_for(t: models.Tournament, tm: models.TournamentMatch) -> int:
    s = {**TOURNAMENT_DEFAULTS, **(t.settings or {})}
    return s["final_legs"] if tour.is_final(t, tm) else s["legs"]


def record_tournament_result(db: Session, t: models.Tournament, tm: models.TournamentMatch,
                             legs1: int, legs2: int) -> None:
    """Ergebnis von Hand: der Sieger muss genau die nötigen Legs haben, der Verlierer weniger."""
    need = legs_for(t, tm)
    if max(legs1, legs2) != need or min(legs1, legs2) >= need or min(legs1, legs2) < 0:
        raise DartsError(f"This match is first to {need} leg{'s' if need != 1 else ''} – "
                         f"the winner has {need}, the other player fewer.")
    tour.set_result(db, t, tm, legs1, legs2)


def tournament_game(db: Session, tm: models.TournamentMatch) -> models.DartsGame | None:
    """Das laufende (oder zuletzt beendete) Spiel zu einem Turnier-Match."""
    return db.scalar(select(models.DartsGame).where(
        models.DartsGame.tournament_match_id == tm.id, models.DartsGame.status != "abandoned")
        .order_by(models.DartsGame.id.desc()))


def start_tournament_game(db: Session, t: models.Tournament, tm: models.TournamentMatch,
                          user: models.User) -> models.DartsGame:
    existing = tournament_game(db, tm)
    if existing is not None and existing.status == "live":
        return existing
    if tm.is_played:
        raise DartsError("This match already has a result.")
    if tm.entry1 is None or tm.entry2 is None:
        raise DartsError("Both players of this match are not known yet.")
    s = {**TOURNAMENT_DEFAULTS, **(t.settings or {})}
    game = create_game(db, s["start"], legs_for(t, tm),
                       [tm.entry1.members[0].competitor_id, tm.entry2.members[0].competitor_id], user)
    game.tournament_match_id = tm.id
    db.commit()
    return game


def _report_to_tournament(db: Session, game: models.DartsGame, state: GameState) -> None:
    """Spielende -> Ergebnis ins Turnier übernehmen (ohne eigenen Commit, passiert in add_visit)."""
    if not game.tournament_match_id:
        return
    tm = db.get(models.TournamentMatch, game.tournament_match_id)
    t = db.get(models.Tournament, tm.tournament_id)
    if tm is None or tm.is_played or tm.entry1 is None or tm.entry2 is None:
        return
    first = game.players[0].competitor_id == tm.entry1.members[0].competitor_id
    l1, l2 = (state.legs_won[0], state.legs_won[1]) if first else (state.legs_won[1], state.legs_won[0])
    tour.advance_winner(t, tm, tm.entry1_id if l1 > l2 else tm.entry2_id, l1, l2)
