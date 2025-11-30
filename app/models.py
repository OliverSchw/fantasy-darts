from sqlalchemy import Column, Integer, String, Float, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from .database import Base


class Player(Base):
    __tablename__ = "players"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    price = Column(Float)
    nation = Column(String)
    seed = Column(Integer, nullable=True)
    points = Column(Float, default=0)
    eliminated = Column(Boolean, default=False)
    champion = Column(Boolean, default=False)

    team_players = relationship("TeamPlayer", back_populates="player")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    password_hash = Column(String)
    is_admin = Column(Boolean, default=False)

    active_team_id = Column(
        Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    active_team = relationship("Team", foreign_keys=[active_team_id], uselist=False)
    teams = relationship(
        "Team",
        back_populates="user",
        foreign_keys="[Team.user_id]",
    )


class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    # user_id = Column(Integer, ForeignKey("users.id"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    user = relationship("User", back_populates="teams", foreign_keys=[user_id])
    team_players = relationship(
        "TeamPlayer",
        back_populates="team",
        # NEU: Kaskadiert die Löschung an die TeamPlayer-Einträge
        cascade="all, delete-orphan",
    )
    champion_id = Column(Integer, ForeignKey("players.id"))
    team_champion_guess = relationship(
        "Player", foreign_keys=[champion_id], uselist=False
    )


class TeamPlayer(Base):
    __tablename__ = "team_players"
    team_id = Column(Integer, ForeignKey("teams.id"), primary_key=True)
    player_id = Column(Integer, ForeignKey("players.id"), primary_key=True)
    is_captain = Column(Boolean, default=False)
    is_underdog = Column(Boolean, default=False)
    # champion = Column(Boolean, default=False)

    team = relationship("Team", back_populates="team_players")
    player = relationship("Player", back_populates="team_players")


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(String, unique=True, index=True)

    # Nur IDs speichern
    p1_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    p2_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    winner_id = Column(Integer, ForeignKey("players.id"), nullable=True)

    # Stats
    sets_p1 = Column(Integer, default=0)
    sets_p2 = Column(Integer, default=0)
    # legs_p1 = Column(Integer, default=0)
    # legs_p2 = Column(Integer, default=0)
    # average_p1 = Column(Float, default=0.0)
    # average_p2 = Column(Float, default=0.0)
    # checkout_pct_p1 = Column(Float, default=0.0)
    # checkout_pct_p2 = Column(Float, default=0.0)
    p161finishes_p1 = Column(Integer, default=0)
    p161finishes_p2 = Column(Integer, default=0)
    p171s_p1 = Column(Integer, default=0)
    p171s_p2 = Column(Integer, default=0)
    ninedarter_p1 = Column(Integer, default=0)
    ninedarter_p2 = Column(Integer, default=0)


class Config(Base):
    """
    Datenbankmodell für globale Konfigurationseinstellungen.
    Wird verwendet, um den globalen 'teams_locked' Status zu speichern.
    """

    __tablename__ = "global_config"  # Der Name der Datenbanktabelle

    # Muss ein Primary Key sein
    id = Column(Integer, primary_key=True, index=True)

    # Der Schlüssel der Einstellung (z.B. 'teams_locked')
    key = Column(String, unique=True, index=True, nullable=False)

    # Der Wert der Einstellung (Boolean ist ideal für True/False Status)
    # Wenn Sie kompliziertere Werte speichern wollen, nutzen Sie String und JSON Serialisierung.
    value = Column(Boolean, default=False, nullable=False)
