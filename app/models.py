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

    team_players = relationship("TeamPlayer", back_populates="player")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    password_hash = Column(String)
    teams = relationship("Team", back_populates="user")


class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    user_id = Column(Integer, ForeignKey("users.id"))

    user = relationship("User", back_populates="teams")
    team_players = relationship("TeamPlayer", back_populates="team")


class TeamPlayer(Base):
    __tablename__ = "team_players"
    team_id = Column(Integer, ForeignKey("teams.id"), primary_key=True)
    player_id = Column(Integer, ForeignKey("players.id"), primary_key=True)
    is_captain = Column(Boolean, default=False)
    is_underdog = Column(Boolean, default=False)

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
    legs_p1 = Column(Integer, default=0)
    legs_p2 = Column(Integer, default=0)
    average_p1 = Column(Float, default=0.0)
    average_p2 = Column(Float, default=0.0)
    checkout_pct_p1 = Column(Float, default=0.0)
    checkout_pct_p2 = Column(Float, default=0.0)
    high_checkout_p1 = Column(Integer, default=0)
    high_checkout_p2 = Column(Integer, default=0)
    d180s_p1 = Column(Integer, default=0)
    d180s_p2 = Column(Integer, default=0)
