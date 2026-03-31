from typing import List, Literal, Optional

from pydantic import BaseModel, Field

ActionType = Literal["fold", "check", "call", "bet", "raise", "raise_to"]


class CreateMatchRequest(BaseModel):
    player_ids: List[str]
    starting_stack: int = Field(default=1000, ge=1)
    small_blind: int = Field(default=10, ge=1)
    big_blind: int = Field(default=20, ge=2)
    turn_timeout_seconds: int = Field(default=15, ge=2, le=120)
    event_log_limit: int = Field(default=2000, ge=100, le=100000)


class SubmitActionRequest(BaseModel):
    player_id: Optional[str] = None
    action: ActionType
    amount: Optional[int] = Field(default=None, ge=1)
    turn_id: Optional[int] = Field(default=None, ge=1)
