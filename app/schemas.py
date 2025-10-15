# app/schemas.py
from pydantic import BaseModel
from typing import List


class TeamCreate(BaseModel):
    user_id: int
    team_name: str
    player_ids: List[int]


from typing import Optional
from pydantic import BaseModel


class MatchResult(BaseModel):
    match_id: str
    p1_id: int
    p2_id: int
    winner_id: Optional[int] = None

    sets_p1: Optional[int] = 0
    sets_p2: Optional[int] = 0
    legs_p1: Optional[int] = 0
    legs_p2: Optional[int] = 0
    average_p1: Optional[float] = 0.0
    average_p2: Optional[float] = 0.0
    checkout_pct_p1: Optional[float] = 0.0
    checkout_pct_p2: Optional[float] = 0.0
    high_checkout_p1: Optional[int] = 0
    high_checkout_p2: Optional[int] = 0
    _180s_p1: Optional[int] = 0
    _180s_p2: Optional[int] = 0

    class Config:
        from_attributes = True
