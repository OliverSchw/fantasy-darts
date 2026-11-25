"""Datenbankmodell.

Wichtig: Punkte werden NICHT gespeichert. Sie werden immer aus den Matches und
den Regeln (rules.toml) berechnet - dadurch kann nichts mehr "aus dem Takt" geraten.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Gesetzt, sobald ein Profilbild existiert. Steht in der Bild-URL, damit Browser-Caches bei
    # einem neuen Bild sofort das neue laden (das Bild selbst liegt in "avatars").
    avatar_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    teams: Mapped[list["Team"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    push_subscriptions: Mapped[list["PushSubscription"]] = relationship(cascade="all, delete-orphan")


class Season(Base):
    """Eine Saison = ein Turnier. Die Regeln liegen in seasons/<key>/rules.toml."""

    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True)
    teams_locked: Mapped[bool] = mapped_column(Boolean, default=False)


class Player(Base):
    __tablename__ = "players"
    __table_args__ = (UniqueConstraint("season_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    nation: Mapped[str] = mapped_column(String(60), default="")
    price: Mapped[float] = mapped_column(Float)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Match(Base):
    """Ein Match im Turnierbaum, adressiert über (round, slot).

    round 1..N, slot 0..(Matches in der Runde - 1).
    Der Sieger von (r, s) spielt in (r+1, s // 2), als p1 wenn s gerade ist, sonst p2.
    """

    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("season_id", "round", "slot"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), index=True)
    round: Mapped[int] = mapped_column(Integer)
    slot: Mapped[int] = mapped_column(Integer)

    p1_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    p2_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)

    sets_p1: Mapped[int] = mapped_column(Integer, default=0)
    sets_p2: Mapped[int] = mapped_column(Integer, default=0)
    # Zusatzstatistiken als {stat_key: anzahl}. Welche Stats es gibt, steht in rules.toml.
    stats_p1: Mapped[dict] = mapped_column(JSON, default=dict)
    stats_p2: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Geplante Anstoßzeit (vom Admin oder später automatisch eingetragen)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    p1: Mapped[Player | None] = relationship(foreign_keys=[p1_id])
    p2: Mapped[Player | None] = relationship(foreign_keys=[p2_id])

    @property
    def is_played(self) -> bool:
        return self.winner_id is not None


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("season_id", "name"),
        # Pro User und Saison darf höchstens ein Team aktiv sein.
        Index(
            "uq_one_active_team",
            "season_id",
            "user_id",
            unique=True,
            sqlite_where=text("is_active"),
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)

    playmaker_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    underdog_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    champion_pick_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="teams")
    members: Mapped[list["TeamPlayer"]] = relationship(cascade="all, delete-orphan", lazy="selectin")

    @property
    def player_ids(self) -> list[int]:
        return [m.player_id for m in self.members]


class TeamPlayer(Base):
    __tablename__ = "team_players"

    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)


class AppSetting(Base):
    """Einstellungen, die der Admin in der Oberfläche ändert (Einladungscode, Regel-Anpassungen ...)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)


class Invite(Base):
    """Persönlicher Einladungslink: genau eine Registrierung, danach verbraucht."""

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(40), unique=True)
    note: Mapped[str] = mapped_column(String(60), default="")  # nur für den Admin sichtbar
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    used_by: Mapped[User | None] = relationship()


class Avatar(Base):
    """Profilbild eines Users: 256x256 WebP, liegt in der DB (Vercel hat kein dauerhaftes Dateisystem)."""

    __tablename__ = "avatars"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    image: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PushSubscription(Base):
    """Ein Gerät (Browser/installierte App), das Push-Benachrichtigungen bekommt - siehe app/push.py."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------------------------------------------------------------- Kern: Teilnehmer an Spielen
# Ein Teilnehmer kann ein Konto haben (user_id) oder ein Gast sein (nur Name). Darts und
# Bierpong benutzen dieselben Teilnehmer, damit Stats später einem Konto zugeordnet werden können.


class Competitor(Base):
    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40))  # Gastname; bei Konten der Username beim Anlegen
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    bot_level: Mapped[str | None] = mapped_column(String(10), nullable=True)  # gesetzt = Darts-Bot (easy ... pro)

    user: Mapped[User | None] = relationship(lazy="joined")

    @property
    def display_name(self) -> str:
        return self.user.username if self.user else self.name

    @property
    def is_guest(self) -> bool:
        return self.user_id is None and not self.bot_level

    @property
    def is_bot(self) -> bool:
        return bool(self.bot_level)


# ---------------------------------------------------------------- Darts (X01)


class DartsGame(Base):
    __tablename__ = "darts_games"

    id: Mapped[int] = mapped_column(primary_key=True)
    start_score: Mapped[int] = mapped_column(Integer, default=501)
    legs_to_win: Mapped[int] = mapped_column(Integer, default=1)
    team_size: Mapped[int] = mapped_column(Integer, default=1)  # 2 = Doppel (A1, B1, A2, B2)
    mode: Mapped[str] = mapped_column(String(12), default="x01")  # x01 | cricket | atc | shanghai | killer
    options: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # z. B. Killer: Zahlen und Leben
    status: Mapped[str] = mapped_column(String(12), default="live")  # live | finished | abandoned
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("competitors.id"), nullable=True)  # bei Doppel: 1. Spieler
    winner_side: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0, 1 ... (Seite = Position % Seiten)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tournament_match_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament_matches.id", ondelete="SET NULL"), nullable=True, index=True)

    players: Mapped[list["DartsGamePlayer"]] = relationship(
        cascade="all, delete-orphan", order_by="DartsGamePlayer.position", lazy="selectin")
    visits: Mapped[list["DartsVisit"]] = relationship(
        cascade="all, delete-orphan", order_by="DartsVisit.seq", lazy="selectin")
    winner: Mapped[Competitor | None] = relationship(foreign_keys=[winner_id])

    @property
    def n_sides(self) -> int:
        return max(1, len(self.players) // (self.team_size or 1))

    def side_of(self, position: int) -> int:
        return position % self.n_sides

    def side_players(self, side: int) -> list["DartsGamePlayer"]:
        return [p for p in self.players if self.side_of(p.position) == side]

    def side_name(self, side: int) -> str:
        return " & ".join(p.competitor.display_name for p in self.side_players(side))

    @property
    def winning_side(self) -> int | None:
        """Gewinner-Seite (auch für ältere Spiele ohne winner_side)."""
        if self.winner_side is not None:
            return self.winner_side
        p = next((p for p in self.players if p.competitor_id == self.winner_id), None)
        return self.side_of(p.position) if p else None

    @property
    def has_bot(self) -> bool:
        """Spiel gegen einen Bot = Training: zählt nicht für Elo, Siege und Neuigkeiten."""
        return any(p.competitor.is_bot for p in self.players)

    def won_by(self, competitor_id: int) -> bool:
        side = self.winning_side
        return side is not None and any(p.competitor_id == competitor_id for p in self.side_players(side))


class DartsGamePlayer(Base):
    __tablename__ = "darts_game_players"

    game_id: Mapped[int] = mapped_column(ForeignKey("darts_games.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)  # Wurfreihenfolge, 0 = Anwurf im 1. Leg
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), index=True)

    competitor: Mapped[Competitor] = relationship(lazy="joined")


class DartsVisit(Base):
    """Eine Aufnahme (bis zu 3 Darts). Der Spielstand wird aus allen Aufnahmen nachgespielt."""

    __tablename__ = "darts_visits"
    __table_args__ = (UniqueConstraint("game_id", "seq"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("darts_games.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # 0, 1, 2 ... - schützt vor doppelt abgeschickten Eingaben
    leg_no: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), index=True)
    score: Mapped[int] = mapped_column(Integer)  # gezählte Punkte, 0 bei Bust
    darts: Mapped[int] = mapped_column(Integer, default=3)
    bust: Mapped[bool] = mapped_column(Boolean, default=False)
    checkout: Mapped[bool] = mapped_column(Boolean, default=False)
    remaining_before: Mapped[int] = mapped_column(Integer)
    throws: Mapped[list | None] = mapped_column(JSON, nullable=True)  # Partyspiele: Dart-Codes, z. B. ["T20", "S5", "M"]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------------------------------------------------------------- Kern: Turniere (K.-o.)
# Gemeinsam für Darts und Bierpong. Ein Eintrag ist ein Spieler (Darts) oder ein Team (Bierpong).


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    sport: Mapped[str] = mapped_column(String(20), index=True)  # "darts" | "beerpong"
    name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(12), default="running")  # running | finished
    settings: Mapped[dict] = mapped_column(JSON, default=dict)  # z. B. {"start": 501, "legs": 2, "final_legs": 3}
    winner_entry_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    entries: Mapped[list["TournamentEntry"]] = relationship(
        cascade="all, delete-orphan", order_by="TournamentEntry.seed", lazy="selectin")
    matches: Mapped[list["TournamentMatch"]] = relationship(
        cascade="all, delete-orphan", order_by="(TournamentMatch.round, TournamentMatch.slot)", lazy="selectin")

    @property
    def num_rounds(self) -> int:
        """Anzahl K.-o.-Runden (0, solange die Gruppenphase läuft)."""
        return max((m.round for m in self.matches if m.group_no is None), default=0)

    @property
    def has_groups(self) -> bool:
        """Gruppenphase (auch eine Liga ist eine einzige Gruppe - nur ohne K.-o. danach)."""
        return (self.settings or {}).get("format") in ("groups", "league")

    @property
    def is_league(self) -> bool:
        """Liga: jeder gegen jeden (optional mit Rückrunde) nach Spieltagen, Tabellenerster gewinnt."""
        return (self.settings or {}).get("format") == "league"

    @property
    def matchdays(self) -> int:
        return max((m.matchday or 0 for m in self.group_matches), default=0)

    @property
    def group_matches(self) -> list["TournamentMatch"]:
        return [m for m in self.matches if m.group_no is not None]

    @property
    def ko_matches(self) -> list["TournamentMatch"]:
        return [m for m in self.matches if m.group_no is None]


class TournamentEntry(Base):
    __tablename__ = "tournament_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    seed: Mapped[int] = mapped_column(Integer)  # 1 = Topgesetzt
    name: Mapped[str | None] = mapped_column(String(60), nullable=True)  # Teamname (Bierpong)
    group_no: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0 = Gruppe A, 1 = B ... (nur mit Gruppenphase)

    members: Mapped[list["TournamentEntryMember"]] = relationship(
        cascade="all, delete-orphan", order_by="TournamentEntryMember.position", lazy="selectin")

    @property
    def competitors(self) -> list[Competitor]:
        return [m.competitor for m in self.members]

    @property
    def display_name(self) -> str:
        return self.name or " & ".join(c.display_name for c in self.competitors)


class TournamentEntryMember(Base):
    __tablename__ = "tournament_entry_members"

    entry_id: Mapped[int] = mapped_column(ForeignKey("tournament_entries.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), index=True)

    competitor: Mapped[Competitor] = relationship(lazy="joined")


class TournamentMatch(Base):
    """Ein Match im K.-o.-Baum, adressiert über (round, slot) - wie bei Fantasy Darts:
    der Sieger von (r, s) spielt in (r+1, s // 2), als Seite 1 wenn s gerade ist, sonst Seite 2.

    Gruppenspiele haben round = 0, eine Gruppennummer (group_no) und eine laufende Nummer als slot."""

    __tablename__ = "tournament_matches"
    __table_args__ = (UniqueConstraint("tournament_id", "round", "slot"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    round: Mapped[int] = mapped_column(Integer)
    slot: Mapped[int] = mapped_column(Integer)
    entry1_id: Mapped[int | None] = mapped_column(ForeignKey("tournament_entries.id"), nullable=True)
    entry2_id: Mapped[int | None] = mapped_column(ForeignKey("tournament_entries.id"), nullable=True)
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("tournament_entries.id"), nullable=True)
    score1: Mapped[int] = mapped_column(Integer, default=0)  # Legs (Darts) bzw. Becher (Bierpong)
    score2: Mapped[int] = mapped_column(Integer, default=0)
    bye: Mapped[bool] = mapped_column(Boolean, default=False)  # Freilos: Gegner fehlt, Sieger steht fest
    group_no: Mapped[int | None] = mapped_column(Integer, nullable=True)  # gesetzt = Gruppenspiel
    board: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Scheibe/Tisch (1, 2 ...), automatisch zugeteilt
    matchday: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Spieltag (1, 2 ...) der Gruppen-/Ligaspiele
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    entry1: Mapped[TournamentEntry | None] = relationship(foreign_keys=[entry1_id], lazy="joined")
    entry2: Mapped[TournamentEntry | None] = relationship(foreign_keys=[entry2_id], lazy="joined")

    @property
    def is_played(self) -> bool:
        return self.winner_id is not None


# ---------------------------------------------------------------- Bierpong


class BeerpongGame(Base):
    __tablename__ = "beerpong_games"

    id: Mapped[int] = mapped_column(primary_key=True)
    cups: Mapped[int] = mapped_column(Integer, default=10)  # Becher pro Seite
    hits1: Mapped[int] = mapped_column(Integer, default=0)  # von Team 1 getroffene Becher
    hits2: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="live")  # live | finished | abandoned
    winner_side: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1 oder 2
    version: Mapped[int] = mapped_column(Integer, default=0)  # zählt jede Änderung (Live-Ansicht, Doppel-Tipps)
    team1_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    team2_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tournament_match_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament_matches.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    players: Mapped[list["BeerpongGamePlayer"]] = relationship(
        cascade="all, delete-orphan", order_by="(BeerpongGamePlayer.side, BeerpongGamePlayer.position)", lazy="selectin")

    def side_players(self, side: int) -> list[Competitor]:
        return [p.competitor for p in self.players if p.side == side]

    def team_name(self, side: int) -> str:
        name = self.team1_name if side == 1 else self.team2_name
        return name or " & ".join(c.display_name for c in self.side_players(side))


class BeerpongGamePlayer(Base):
    __tablename__ = "beerpong_game_players"

    game_id: Mapped[int] = mapped_column(ForeignKey("beerpong_games.id", ondelete="CASCADE"), primary_key=True)
    side: Mapped[int] = mapped_column(Integer, primary_key=True)  # 1 oder 2
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), index=True)

    competitor: Mapped[Competitor] = relationship(lazy="joined")


class LoginThrottle(Base):
    """Fehlgeschlagene Logins pro Username (in der DB, damit es auch auf mehreren Server-Instanzen wirkt)."""

    __tablename__ = "login_throttle"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)  # Username in Kleinbuchstaben
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
