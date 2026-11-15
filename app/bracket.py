"""Ergebnisse eintragen/löschen und Sieger im Turnierbaum weiterreichen."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .rules import Rules


class BracketError(ValueError):
    pass


def _next_match(db: Session, m: models.Match) -> tuple[models.Match | None, str]:
    side = "p1_id" if m.slot % 2 == 0 else "p2_id"
    nxt = db.scalar(
        select(models.Match).where(
            models.Match.season_id == m.season_id,
            models.Match.round == m.round + 1,
            models.Match.slot == m.slot // 2,
        )
    )
    return nxt, side


def validate_sets(rules: Rules, round_no: int, sets_p1: int, sets_p2: int) -> int:
    """Gibt 1 oder 2 zurück (wer gewonnen hat) oder wirft BracketError."""
    target = rules.tournament.sets_to_win[round_no - 1]
    if sets_p1 < 0 or sets_p2 < 0:
        raise BracketError("Sets can't be negative.")
    if sets_p1 == target and sets_p2 < target:
        return 1
    if sets_p2 == target and sets_p1 < target:
        return 2
    raise BracketError(f"In this round the winner needs exactly {target} sets, the loser fewer.")


def save_result(
    db: Session,
    rules: Rules,
    m: models.Match,
    sets_p1: int,
    sets_p2: int,
    stats_p1: dict[str, int],
    stats_p2: dict[str, int],
) -> None:
    if m.p1_id is None or m.p2_id is None:
        raise BracketError("Both players of this match are not known yet.")
    winner = m.p1_id if validate_sets(rules, m.round, sets_p1, sets_p2) == 1 else m.p2_id

    nxt, side = _next_match(db, m)
    if nxt is not None and m.winner_id is not None and winner != m.winner_id and nxt.is_played:
        raise BracketError("Changing the winner is not possible while the follow-up match has a result. Delete that one first.")

    keys = {s.key for s in rules.scoring.stats}
    m.sets_p1, m.sets_p2 = sets_p1, sets_p2
    m.stats_p1 = {k: max(0, int(v)) for k, v in stats_p1.items() if k in keys}
    m.stats_p2 = {k: max(0, int(v)) for k, v in stats_p2.items() if k in keys}
    m.winner_id = winner
    m.updated_at = datetime.now(timezone.utc)
    if nxt is not None:
        setattr(nxt, side, winner)
    db.commit()


def delete_result(db: Session, m: models.Match) -> None:
    nxt, side = _next_match(db, m)
    if nxt is not None and nxt.is_played:
        raise BracketError("Delete the result of the follow-up match first.")
    m.winner_id = None
    m.sets_p1 = m.sets_p2 = 0
    m.stats_p1, m.stats_p2 = {}, {}
    m.updated_at = datetime.now(timezone.utc)
    if nxt is not None:
        setattr(nxt, side, None)
    db.commit()
