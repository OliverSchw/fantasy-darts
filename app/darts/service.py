"""Darts: Datenbank-Operationen rund um Teilnehmer, Spiele und Aufnahmen."""

import random
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from .. import models
from .. import tournaments as tour
from .engine import DartsError, GameState, Visit, advance, make_visit, new_state, replay
from .modes import apply_visit, new_mode_state, replay_mode
from .bot import LEVELS, bot_visit
from .throws import x01_visit


# ---------------------------------------------------------------- Spiele


def create_game(db: Session, start: int, legs_to_win: int, competitor_ids: list[int],
                created_by: models.User | None, team_size: int = 1) -> models.DartsGame:
    """competitor_ids in Wurfreihenfolge; Doppel (team_size 2): Team 1 = Positionen 0 und 2, Team 2 = 1 und 3.
    Bots dürfen mitspielen (mindestens ein Mensch) - sie werfen automatisch, sobald sie dran sind."""
    if len(set(competitor_ids)) != len(competitor_ids):
        raise DartsError("Each player can only take part once.")
    new_state(start, legs_to_win, len(competitor_ids), team_size)  # prüft Start, Legs, Spielerzahl, Teams
    found = {c.id: c for c in db.scalars(select(models.Competitor).where(models.Competitor.id.in_(competitor_ids)))}
    if set(found) != set(competitor_ids):
        raise DartsError("Unknown player.")
    if all(c.is_bot for c in found.values()):
        raise DartsError("Add at least one human player – bots only play against people.")
    game = models.DartsGame(start_score=start, legs_to_win=legs_to_win, team_size=team_size,
                            created_by_id=created_by.id if created_by else None)
    game.players = [models.DartsGamePlayer(position=i, competitor_id=cid) for i, cid in enumerate(competitor_ids)]
    db.add(game)
    db.commit()
    play_bots(db, game)  # wirft ein Bot zuerst?
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


bot_rng = random.Random()  # Tests setzen hier einen festen Startwert


def _bot_to_throw(game: models.DartsGame, state: GameState):
    """Der Bot, der gerade dran ist (sonst None)."""
    if game.status != "live" or state.finished:
        return None
    c = game.players[state.turn].competitor
    return LEVELS.get(c.bot_level) if c.bot_level else None


def play_bots(db: Session, game: models.DartsGame) -> list[models.DartsVisit]:
    """Alle Bots werfen lassen, bis wieder ein Mensch dran ist (oder das Spiel vorbei ist)."""
    thrown = []
    for _ in range(200):  # Sicherheitsgrenze
        state = game_state(game)
        level = _bot_to_throw(game, state)
        if level is None:
            break
        _store_visit(db, game, state, None, None, len(game.visits), bot_visit(state, level, bot_rng))
        thrown.append(game.visits[-1])
    return thrown


def add_visit(db: Session, game: models.DartsGame, score: int | None, darts: int | None, seq: int,
              throws: list[str] | None = None) -> Visit:
    """Speichert die nächste Aufnahme. seq = Anzahl Aufnahmen, die die Seite kannte (gegen Doppel-Tipps).
    Mit throws (Dart für Dart, z. B. ["T20", "T20", "D20"]) werden Punkte und Darts daraus bestimmt."""
    if game.status != "live":
        raise DartsError("This game is not running any more.")
    if seq != len(game.visits):
        raise StaleGame("The game was updated in the meantime – here is the latest score.")
    state = game_state(game)
    if _bot_to_throw(game, state):
        raise DartsError("It's the bot's turn.")
    visit = _store_visit(db, game, state, score, darts, seq, throws)
    play_bots(db, game)
    return visit


def _store_visit(db: Session, game: models.DartsGame, state: GameState, score: int | None, darts: int | None,
                 seq: int, throws: list[str] | None) -> Visit:
    if throws:
        throws = [t.strip().upper() for t in throws]
        visit = x01_visit(state, throws)
    else:
        throws = None
        visit = make_visit(state, score, darts)
    db.add(models.DartsVisit(
        game_id=game.id, seq=seq, leg_no=state.leg_no, position=visit.player,
        competitor_id=game.players[visit.player].competitor_id, score=visit.score, darts=visit.darts,
        bust=visit.bust, checkout=visit.checkout, remaining_before=state.remaining[state.side(visit.player)],
        throws=throws,
    ))
    advance(state, visit)  # Stand fortschreiben, um das Spielende zu erkennen
    if state.finished:
        game.status = "finished"
        game.winner_side = state.winner
        game.winner_id = game.side_players(state.winner)[0].competitor_id
        game.finished_at = datetime.now(timezone.utc)
        _report_to_tournament(db, game, (state.legs_won[0], state.legs_won[1]) if state.n_sides > 1 else (1, 0))
    try:
        db.commit()
    except IntegrityError:  # gleichzeitig dieselbe Aufnahme von zwei Handys
        db.rollback()
        raise StaleGame("The game was updated in the meantime – here is the latest score.") from None
    db.refresh(game)
    return visit


def undo_last(db: Session, game: models.DartsGame) -> bool:
    """Letzte Aufnahme löschen. Ein beendetes Spiel läuft danach wieder.
    Gegen Bots: deren Aufnahmen danach und die letzte eigene Aufnahme werden zurückgenommen."""
    if game.status == "abandoned" or not game.visits:
        return False
    if game.has_bot:
        bots = {p.position for p in game.players if p.competitor.is_bot}
        human = [i for i, v in enumerate(game.visits) if v.position not in bots]
        if not human:
            return False
        for v in game.visits[human[-1]:]:
            db.delete(v)
        game.status, game.winner_id, game.winner_side, game.finished_at = "live", None, None, None
        db.commit()
        db.refresh(game)
        return True
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


TOURNAMENT_DEFAULTS = {"start": 501, "legs": 2, "final_legs": 3, "mode": "x01", "team_size": 1}


def tournament_settings(t: models.Tournament) -> dict:
    return {**TOURNAMENT_DEFAULTS, **(t.settings or {})}


def legs_for(t: models.Tournament, tm: models.TournamentMatch) -> int:
    """Wie viele Legs ein Match braucht (Partyspiele: ein Spiel = ein "Leg")."""
    s = tournament_settings(t)
    if s["mode"] != "x01":
        return 1
    return s["final_legs"] if tour.is_final(t, tm) else s["legs"]


def record_tournament_result(db: Session, t: models.Tournament, tm: models.TournamentMatch,
                             legs1: int, legs2: int) -> None:
    """Ergebnis von Hand: der Sieger muss genau die nötigen Legs haben, der Verlierer weniger."""
    need = legs_for(t, tm)
    if max(legs1, legs2) != need or min(legs1, legs2) >= need or min(legs1, legs2) < 0:
        if need == 1 and tournament_settings(t)["mode"] != "x01":
            raise DartsError("Enter 1 for the winner and 0 for the other side.")
        raise DartsError(f"This match is first to {need} leg{'s' if need != 1 else ''} – "
                         f"the winner has {need}, the other side fewer.")
    tour.set_result(db, t, tm, legs1, legs2)


def tournament_game(db: Session, tm: models.TournamentMatch) -> models.DartsGame | None:
    """Das laufende (oder zuletzt beendete) Spiel zu einem Turnier-Match."""
    return db.scalar(select(models.DartsGame).where(
        models.DartsGame.tournament_match_id == tm.id, models.DartsGame.status != "abandoned")
        .order_by(models.DartsGame.id.desc()))


def start_tournament_game(db: Session, t: models.Tournament, tm: models.TournamentMatch,
                          user: models.User) -> models.DartsGame:
    """Spiel zum Match anlegen. Eintrag 1 wirft immer zuerst (Position 0 = Seite 0)."""
    existing = tournament_game(db, tm)
    if existing is not None and existing.status == "live":
        return existing
    if tm.is_played:
        raise DartsError("This match already has a result.")
    if tm.entry1 is None or tm.entry2 is None:
        raise DartsError("Both sides of this match are not known yet.")
    s = tournament_settings(t)
    a, b = [m.competitor_id for m in tm.entry1.members], [m.competitor_id for m in tm.entry2.members]
    if s["mode"] != "x01":
        opts = {"lives": s.get("lives", 3)} if s["mode"] == "killer" else (
            {"rounds": s.get("rounds", 7)} if s["mode"] == "shanghai" else {})
        game = create_mode_game(db, s["mode"], [a[0], b[0]], user, opts)
    elif s["team_size"] == 2:
        if len(a) != 2 or len(b) != 2:
            raise DartsError("Doubles need two players per team.")
        game = create_game(db, s["start"], legs_for(t, tm), [a[0], b[0], a[1], b[1]], user, team_size=2)
    else:
        game = create_game(db, s["start"], legs_for(t, tm), [a[0], b[0]], user)
    game.tournament_match_id = tm.id
    db.commit()
    return game


def _report_to_tournament(db: Session, game: models.DartsGame, side_scores: tuple[int, int]) -> None:
    """Spielende -> Ergebnis ins Turnier übernehmen (ohne eigenen Commit). side_scores = (Seite 0, Seite 1)."""
    if not game.tournament_match_id:
        return
    tm = db.get(models.TournamentMatch, game.tournament_match_id)
    if tm is None or tm.is_played or tm.entry1 is None or tm.entry2 is None:
        return  # Turnier gelöscht oder Match schon entschieden
    t = db.get(models.Tournament, tm.tournament_id)
    entry1_ids = {m.competitor_id for m in tm.entry1.members}
    first = game.players[0].competitor_id in entry1_ids  # Seite 0 = Eintrag 1 (Normalfall)
    s1, s2 = side_scores if first else (side_scores[1], side_scores[0])
    tour.advance_winner(t, tm, tm.entry1_id if s1 > s2 else tm.entry2_id, s1, s2)


# ---------------------------------------------------------------- Partyspiele (Cricket, Around the Clock, ...)


def create_mode_game(db: Session, mode: str, competitor_ids: list[int], created_by: models.User | None,
                     options: dict | None = None) -> models.DartsGame:
    if len(set(competitor_ids)) != len(competitor_ids):
        raise DartsError("Each player can only take part once.")
    options = dict(options or {})
    if mode == "killer":
        options["numbers"] = random.sample(range(1, 21), len(competitor_ids))
        options.setdefault("lives", 3)
    new_mode_state(mode, len(competitor_ids), options)  # prüft Spielerzahl und Optionen
    found = {c.id for c in db.scalars(select(models.Competitor).where(models.Competitor.id.in_(competitor_ids)))}
    if found != set(competitor_ids):
        raise DartsError("Unknown player.")
    game = models.DartsGame(mode=mode, options=options, start_score=0, legs_to_win=1,
                            created_by_id=created_by.id if created_by else None)
    game.players = [models.DartsGamePlayer(position=i, competitor_id=cid) for i, cid in enumerate(competitor_ids)]
    db.add(game)
    db.commit()
    return game


def mode_state(game: models.DartsGame):
    return replay_mode(game.mode, len(game.players), game.options or {}, [v.throws or [] for v in game.visits])


def add_mode_visit(db: Session, game: models.DartsGame, throws: list[str], seq: int) -> dict:
    if game.status != "live":
        raise DartsError("This game is not running any more.")
    if seq != len(game.visits):
        raise StaleGame("The game was updated in the meantime – here is the latest score.")
    state = mode_state(game)
    player = state.turn
    result = apply_visit(state, throws)
    db.add(models.DartsVisit(
        game_id=game.id, seq=seq, leg_no=1, position=player, competitor_id=game.players[player].competitor_id,
        score=result["points"], darts=len(throws), checkout=result["won"], remaining_before=0, throws=throws,
    ))
    if state.finished:
        game.status, game.winner_side = "finished", state.winner
        game.winner_id = game.players[state.winner].competitor_id
        game.finished_at = datetime.now(timezone.utc)
        if len(game.players) == 2:
            _report_to_tournament(db, game, (1, 0) if state.winner == 0 else (0, 1))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise StaleGame("The game was updated in the meantime – here is the latest score.") from None
    db.refresh(game)
    return {**result, "log": state.log}
