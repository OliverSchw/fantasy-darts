"""Spiele bestätigen: Wer im Account "Confirm games I'm added to" einschaltet, muss Spiele, Turniere und Ligen
bestätigen, zu denen ihn jemand anderes hinzufügt. Bis dahin zählt das Spiel für ihn nicht (Stats, Elo,
Erfolge, Neuigkeiten, Hall of Fame). Bestätigen geht jederzeit - auch schon am Anfang.

- Automatisch bestätigt: wer das Spiel selbst anlegt, und wer bei "Own phones" selbst Würfe einträgt.
- Ablehnen ("Not me"): Der Spieler wird in dem Spiel/Turnier durch einen Gast "<Name> (guest)" ersetzt -
  das Ergebnis bleibt für die anderen erhalten, für ihn zählt nichts.
- Bei Turnieren/Ligen gilt eine Bestätigung für das ganze Turnier und alle Spiele darin.
"""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import models, push

KINDS = ("darts", "beerpong", "tournament")


# ---------------------------------------------------------------- Anfragen


def request(db: Session, kind: str, ref_id: int, competitor_ids, added_by: models.User | None,
            title: str, url: str) -> list[int]:
    """Für alle Mitspieler mit eingeschalteter Bestätigung (außer dem, der hinzufügt) eine offene Bestätigung
    anlegen und Bescheid geben. Gibt die User-IDs zurück."""
    if added_by is None:
        return []
    users = db.scalars(select(models.User).join(models.Competitor, models.Competitor.user_id == models.User.id)
                       .where(models.Competitor.id.in_(list(competitor_ids)), models.User.confirm_games.is_(True),
                              models.User.id != added_by.id)).unique().all()
    for u in users:
        if db.scalar(select(models.Confirmation.id).where(models.Confirmation.user_id == u.id,
                                                         models.Confirmation.kind == kind,
                                                         models.Confirmation.ref_id == ref_id)) is None:
            db.add(models.Confirmation(user_id=u.id, kind=kind, ref_id=ref_id, added_by_id=added_by.id))
    if users:
        db.commit()
        try:
            push.send_to_users(db, [u.id for u in users], f"📥 {added_by.username} added you",
                               f"{title} – tap to confirm it counts for you.", "/confirm", tag=f"confirm-{kind}-{ref_id}")
        except Exception:  # Push darf nie das Anlegen stören
            pass
    return [u.id for u in users]


def pending_for(db: Session, user: models.User | None, kind: str | None = None, ref_id: int | None = None):
    if user is None:
        return []
    q = select(models.Confirmation).where(models.Confirmation.user_id == user.id)
    if kind:
        q = q.where(models.Confirmation.kind == kind)
    if ref_id is not None:
        q = q.where(models.Confirmation.ref_id == ref_id)
    return list(db.scalars(q.order_by(models.Confirmation.created_at.desc())))


def count_for(db: Session, user: models.User | None) -> int:
    if user is None:
        return 0
    return db.scalar(select(func.count()).select_from(models.Confirmation)
                     .where(models.Confirmation.user_id == user.id)) or 0


def _tournament_of_game(db: Session, kind: str, ref_id: int) -> int | None:
    model = models.DartsGame if kind == "darts" else models.BeerpongGame
    g = db.get(model, ref_id)
    if g is None or not g.tournament_match_id:
        return None
    tm = db.get(models.TournamentMatch, g.tournament_match_id)
    return tm.tournament_id if tm else None


def accept(db: Session, user: models.User, kind: str, ref_id: int) -> bool:
    """Bestätigen ("das war ich"). Bei einem Turnierspiel gilt das für das ganze Turnier."""
    rows = pending_for(db, user, kind, ref_id)
    if kind in ("darts", "beerpong"):
        tid = _tournament_of_game(db, kind, ref_id)
        if tid:
            rows += pending_for(db, user, "tournament", tid)
    for r in rows:
        db.delete(r)
    db.commit()
    return bool(rows)


def auto_accept(db: Session, user: models.User | None, kind: str, ref_id: int) -> None:
    """Wer selbst zählt, war offensichtlich dabei."""
    if user is not None and user.confirm_games:
        accept(db, user, kind, ref_id)


# ---------------------------------------------------------------- Ablehnen: durch einen Gast ersetzen


def _stand_in(db: Session, user: models.User) -> models.Competitor:
    name = f"{user.username[:32]} (guest)"
    c = db.scalar(select(models.Competitor).where(models.Competitor.name == name, models.Competitor.user_id.is_(None),
                                                  models.Competitor.bot_level.is_(None)))
    if c is None:
        c = models.Competitor(name=name)
        db.add(c)
        db.flush()
    return c


def _swap_darts(db: Session, game_ids: list[int], old: int, new: int) -> None:
    if not game_ids:
        return
    for table in (models.DartsGamePlayer, models.DartsVisit):
        db.execute(update(table).where(table.game_id.in_(game_ids), table.competitor_id == old)
                   .values(competitor_id=new))
    db.execute(update(models.DartsGame).where(models.DartsGame.id.in_(game_ids), models.DartsGame.winner_id == old)
               .values(winner_id=new))


def _swap_beerpong(db: Session, game_ids: list[int], old: int, new: int) -> None:
    if game_ids:
        db.execute(update(models.BeerpongGamePlayer).where(models.BeerpongGamePlayer.game_id.in_(game_ids),
                                                           models.BeerpongGamePlayer.competitor_id == old)
                   .values(competitor_id=new))


def decline(db: Session, user: models.User, kind: str, ref_id: int) -> bool:
    """Ablehnen ("das war ich nicht"): im Spiel bzw. ganzen Turnier durch einen Gast ersetzen."""
    rows = pending_for(db, user, kind, ref_id)
    if not rows:
        return False
    me = db.scalar(select(models.Competitor).where(models.Competitor.user_id == user.id))
    if me is not None:
        guest = _stand_in(db, user)
        if kind == "darts":
            _swap_darts(db, [ref_id], me.id, guest.id)
        elif kind == "beerpong":
            _swap_beerpong(db, [ref_id], me.id, guest.id)
        else:
            t = db.get(models.Tournament, ref_id)
            if t is not None:
                db.execute(update(models.TournamentEntryMember).where(
                    models.TournamentEntryMember.entry_id.in_([e.id for e in t.entries]),
                    models.TournamentEntryMember.competitor_id == me.id).values(competitor_id=guest.id))
                match_ids = [m.id for m in t.matches]
                model = models.DartsGame if t.sport == "darts" else models.BeerpongGame
                games = list(db.scalars(select(model.id).where(model.tournament_match_id.in_(match_ids)))) \
                    if match_ids else []
                (_swap_darts if t.sport == "darts" else _swap_beerpong)(db, games, me.id, guest.id)
    for r in rows:
        db.delete(r)
    db.commit()
    db.expire_all()
    return True


# ---------------------------------------------------------------- Was zählt noch nicht?


def pending_pairs(db: Session, sport: str = "darts") -> set[tuple[int, int]]:
    """{(Spiel-ID, Teilnehmer-ID)}, die noch nicht bestätigt sind - für Stats, Elo, Erfolge, Neuigkeiten."""
    rows = db.execute(select(models.Confirmation.kind, models.Confirmation.ref_id, models.Competitor.id)
                      .join(models.Competitor, models.Competitor.user_id == models.Confirmation.user_id)).all()
    if not rows:
        return set()
    out: set[tuple[int, int]] = set()
    model = models.DartsGame if sport == "darts" else models.BeerpongGame
    tournaments: dict[int, list[int]] = {}
    for kind, ref, cid in rows:
        if kind == sport:
            out.add((ref, cid))
        elif kind == "tournament":
            tournaments.setdefault(ref, []).append(cid)
    if tournaments:
        q = (select(model.id, models.TournamentMatch.tournament_id)
             .join(models.TournamentMatch, models.TournamentMatch.id == model.tournament_match_id)
             .where(models.TournamentMatch.tournament_id.in_(list(tournaments))))
        for gid, tid in db.execute(q):
            out.update((gid, cid) for cid in tournaments[tid])
    return out


def pending_tournament_pairs(db: Session) -> set[tuple[int, int]]:
    """{(Turnier-ID, Teilnehmer-ID)} - für die Hall of Fame."""
    return set(db.execute(select(models.Confirmation.ref_id, models.Competitor.id)
                          .join(models.Competitor, models.Competitor.user_id == models.Confirmation.user_id)
                          .where(models.Confirmation.kind == "tournament")).all())


# ---------------------------------------------------------------- Anzeige


def describe(db: Session, c: models.Confirmation) -> dict | None:
    """Für die Bestätigen-Seite: Titel, Untertitel, Link. None, wenn es das Spiel nicht mehr gibt."""
    if c.kind == "darts":
        g = db.get(models.DartsGame, c.ref_id)
        if g is None:
            return None
        from .darts.modes import MODES
        what = MODES[g.mode]["name"] if g.mode != "x01" else f"Darts {g.start_score}"
        sides = " vs ".join(g.side_name(s) for s in range(g.n_sides))
        return {"icon": "🎯", "title": what, "sub": sides, "url": f"/darts/games/{g.id}", "status": g.status}
    if c.kind == "beerpong":
        g = db.get(models.BeerpongGame, c.ref_id)
        if g is None:
            return None
        return {"icon": "🍺", "title": "Beer pong", "sub": f"{g.team_name(1)} vs {g.team_name(2)}",
                "url": f"/beerpong/games/{g.id}", "status": g.status}
    t = db.get(models.Tournament, c.ref_id)
    if t is None:
        return None
    base = "/beerpong" if t.sport == "beerpong" else "/darts"
    return {"icon": "📋" if t.is_league else "🏆", "title": t.name,
            "sub": ("League" if t.is_league else "Tournament") + f" · {len(t.entries)} entries · all its games",
            "url": f"{base}/tournaments/{t.id}", "status": t.status}
