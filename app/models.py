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
